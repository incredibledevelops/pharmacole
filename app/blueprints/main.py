# app/blueprints/main.py
from datetime import datetime

from flask import (
    Blueprint, render_template, redirect, url_for, request, flash,
    jsonify, abort, current_app, send_from_directory, make_response,
)
from flask_login import current_user, login_required

from models import find_tenant_by_id, find_tenant_by_code
from app.services import tenant_service, auth_service
from extensions import mongo
from utils import oid


main_bp = Blueprint("main", __name__)


# ---------------------------------------------------------------------------
# Public pages
# ---------------------------------------------------------------------------

@main_bp.route("/")
def landing():
    return render_template("landing.html")


@main_bp.route("/dashboard")
def redirect_dashboard():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))

    role = current_user.role
    if role == "owner":
        return redirect(url_for("owner.dashboard"))
    if role == "pharmacist":
        return redirect(url_for("pharmacist.dashboard"))
    if role == "cashier":
        return redirect(url_for("cashier.pos"))
    if role == "super_admin":
        return redirect(url_for("super_admin.dashboard"))
    return redirect(url_for("auth.login"))


# ---------------------------------------------------------------------------
# Subscription flow
# ---------------------------------------------------------------------------

@main_bp.route("/subscription/locked")
def subscription_locked():
    tenant = None
    if current_user.is_authenticated and current_user.tenant_id:
        tenant = find_tenant_by_id(current_user.tenant_id)
    return render_template("errors/subscription_locked.html", tenant=tenant)


@main_bp.route("/subscription/renew", methods=["POST"])
def renew_subscription():
    """
    Record intent to switch/renew tier. Does NOT change the tenant's tier.
    The tier change only takes effect when Paystack confirms payment.
    """
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))

    if current_user.role != "owner":
        flash("Only the owner can renew the subscription.", "warning")
        return redirect(url_for("main.subscription_locked"))

    tenant = find_tenant_by_id(current_user.tenant_id)
    if not tenant:
        flash("Pharmacy record not found.", "danger")
        return redirect(url_for("auth.logout"))

    requested = (request.form.get("tier") or "").strip().lower()
    tiers = current_app.config["PRICING_TIERS"]

    if not requested:
        flash("Please pick a plan to continue.", "warning")
        return redirect(url_for("owner.subscription"))

    if requested not in tiers:
        flash("Unknown plan selected.", "danger")
        return redirect(url_for("owner.subscription"))

    if requested != tenant.tier:
        # set_pending_tier refuses excessive downgrades and returns False.
        ok = tenant_service.set_pending_tier(tenant._id, requested)
        if not ok:
            flash(
                f"Cannot switch to {tiers[requested]['label']} while your "
                "current usage exceeds that plan's limits. Deactivate extra "
                "branches or users first.",
                "danger",
            )
            return redirect(url_for("owner.subscription"))
        flash(
            f"Ready to switch to {tiers[requested]['label']}. "
            "Complete payment to activate the new plan.",
            "info",
        )
    else:
        tenant_service.clear_pending_tier(tenant._id)
        flash(
            f"You're renewing the {tiers[requested]['label']} plan. "
            "Continue to payment to extend your subscription.",
            "info",
        )

    return redirect(url_for("auth.payment"))


@main_bp.route("/subscription/cancel-pending", methods=["POST"])
def cancel_pending_tier():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    if current_user.role != "owner":
        return redirect(url_for("main.subscription_locked"))

    tenant = find_tenant_by_id(current_user.tenant_id)
    if tenant:
        tenant_service.clear_pending_tier(tenant._id)
        flash("Pending plan change cancelled.", "success")

    return redirect(url_for("owner.subscription"))


# ---------------------------------------------------------------------------
# Session token for the browser (mint short-lived JWT from the Flask session)
# ---------------------------------------------------------------------------

@main_bp.route("/api/session-token")
@login_required
def session_token():
    tokens = auth_service.issue_tokens(current_user)

    tenant_code = None
    if current_user.tenant_id:
        t = find_tenant_by_id(current_user.tenant_id)
        tenant_code = t.tenant_code if t else None

    resp = jsonify({
        "access": tokens["access"],
        "expires_in": tokens["expires_in"],
        "api_base": "/api/v1",
        "tenant_code": tenant_code,
    })
    # Never cache a bearer token
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
    resp.headers["Pragma"] = "no-cache"
    return resp


# ---------------------------------------------------------------------------
# Public receipt verification (tenant-scoped)
# ---------------------------------------------------------------------------

@main_bp.route("/r/<receipt_no>")
def verify_receipt_page(receipt_no):
    """
    Public receipt-verification page used by the QR on printed receipts.

    Lookup is tenant-scoped. Accepts:
      1. `?tenant=GH-XXXXXX` (preferred)
      2. A combined key of the form `GH-XXXXXX-RCP-…`
      3. Ambiguous fallback: only if EXACTLY one sale matches across all
         tenants — otherwise 404 (never leak which tenant matched).
    """
    tenant_code = (request.args.get("tenant") or "").strip().upper()
    normalized = (receipt_no or "").strip().upper()

    if not normalized:
        abort(404)

    sale = None
    tenant = None

    # Case 1: explicit tenant param.
    if tenant_code:
        tenant = find_tenant_by_code(tenant_code)
        if tenant:
            sale = mongo.db.sales.find_one({
                "tenant_id": oid(tenant._id),
                "receipt_no": normalized,
            })

    # Case 2: tenant code embedded in the receipt string (GH-XXXXXX-...).
    if sale is None and not tenant_code:
        if normalized.startswith("GH-") and len(normalized) > 9 and normalized[9] == "-":
            tenant = find_tenant_by_code(normalized[:9])
            if tenant:
                sale = mongo.db.sales.find_one({
                    "tenant_id": oid(tenant._id),
                    "receipt_no": normalized[10:],
                })

    # Case 3: unambiguous global match — safe because only 1 match means
    # there's no cross-tenant leak. We then load the full doc so the
    # template can render real fields (Phase 1 had a projection bug here).
    if sale is None:
        matches = list(mongo.db.sales.find(
            {"receipt_no": normalized},
            {"_id": 1},
        ).limit(2))
        if len(matches) == 1:
            sale = mongo.db.sales.find_one({"_id": matches[0]["_id"]})

    if not sale:
        abort(404)

    # Resolve the issuing tenant for the template (nice-to-have: show the
    # pharmacy name on the verification page).
    if tenant is None and sale.get("tenant_id"):
        tenant = find_tenant_by_id(sale["tenant_id"])

    return render_template("receipt_verify.html", sale=sale, tenant=tenant)


# ---------------------------------------------------------------------------
# Health / SEO
# ---------------------------------------------------------------------------

@main_bp.route("/healthz")
def healthz():
    try:
        mongo.db.command("ping")
        return {"status": "ok", "time": datetime.utcnow().isoformat()}, 200
    except Exception:
        current_app.logger.exception("Health check failed")
        return {"status": "degraded"}, 503


@main_bp.route("/robots.txt")
def robots_txt():
    try:
        return send_from_directory(current_app.static_folder, "robots.txt")
    except Exception:
        return make_response("User-agent: *\nAllow: /\n", 200, {
            "Content-Type": "text/plain; charset=utf-8",
        })


@main_bp.route("/sitemap.xml")
def sitemap_xml():
    try:
        return send_from_directory(
            current_app.static_folder, "sitemap.xml",
            mimetype="application/xml",
        )
    except Exception:
        body = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            '</urlset>\n'
        )
        return make_response(body, 200, {
            "Content-Type": "application/xml; charset=utf-8",
        })


@main_bp.route("/favicon.ico")
def favicon():
    try:
        return send_from_directory(
            current_app.static_folder, "favicon.ico",
            mimetype="image/vnd.microsoft.icon",
        )
    except Exception:
        return ("", 204)


# ---------------------------------------------------------------------------
# Trailing-slash normalization
# ---------------------------------------------------------------------------

@main_bp.route("/dashboard/", strict_slashes=False, endpoint="dashboard_slash")
def _dashboard_slash():
    return redirect(url_for("main.redirect_dashboard"))


@main_bp.route("/auth/login/", strict_slashes=False, endpoint="login_slash")
def _login_slash():
    return redirect(url_for("auth.login"))


@main_bp.route("/auth/signup/", strict_slashes=False, endpoint="signup_slash")
def _signup_slash():
    return redirect(url_for("auth.signup"))