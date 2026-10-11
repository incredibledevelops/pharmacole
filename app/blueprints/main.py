# app/blueprints/main.py
from datetime import datetime

from flask import (
    Blueprint, render_template, redirect, url_for, request, flash,
    jsonify, abort, current_app, send_from_directory, make_response,
)
from flask_login import current_user, login_required

from models import find_tenant_by_id
from app.services import tenant_service, auth_service
from extensions import mongo


main_bp = Blueprint("main", __name__)


# ---------------------------------------------------------------------------
# Public pages
# ---------------------------------------------------------------------------

@main_bp.route("/")
def landing():
    return render_template("landing.html")


@main_bp.route("/dashboard")
def redirect_dashboard():
    """Single entry point: send each role to their home page."""
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
        # Record intent; do not modify `tier` yet.
        tenant_service.set_pending_tier(tenant._id, requested)
        flash(
            f"Ready to switch to {tiers[requested]['label']}. "
            "Complete payment to activate the new plan.",
            "info",
        )
    else:
        # Same tier — renewal only; clear any stale pending change.
        tenant_service.clear_pending_tier(tenant._id)
        flash(
            f"You're renewing the {tiers[requested]['label']} plan. "
            "Continue to payment to extend your subscription.",
            "info",
        )

    return redirect(url_for("auth.payment"))


@main_bp.route("/subscription/cancel-pending", methods=["POST"])
def cancel_pending_tier():
    """Explicit 'I changed my mind' — clear the pending tier."""
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
    resp = jsonify({
        "access": tokens["access"],
        "expires_in": tokens["expires_in"],
    })
    # Never cache a bearer token
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
    resp.headers["Pragma"] = "no-cache"
    return resp


# ---------------------------------------------------------------------------
# Public receipt verification
# ---------------------------------------------------------------------------

@main_bp.route("/r/<receipt_no>")
def verify_receipt_page(receipt_no):
    # Normalize: receipts are generated uppercase (RCP-…) but users may type
    # them in any case or paste with stray whitespace.
    normalized = (receipt_no or "").strip().upper()
    sale = mongo.db.sales.find_one({"receipt_no": normalized})
    if not sale:
        abort(404)
    return render_template("receipt_verify.html", sale=sale)


# ---------------------------------------------------------------------------
# Health / SEO
# ---------------------------------------------------------------------------

@main_bp.route("/healthz")
def healthz():
    try:
        mongo.db.command("ping")
        return {"status": "ok", "time": datetime.utcnow().isoformat()}, 200
    except Exception as e:
        # Log the real reason server-side; don't leak internals to the caller.
        current_app.logger.exception("Health check failed")
        return {"status": "degraded"}, 503


@main_bp.route("/robots.txt")
def robots_txt():
    try:
        return send_from_directory(current_app.static_folder, "robots.txt")
    except Exception:
        # Fail soft — a missing robots.txt should never 500 the site.
        return make_response("User-agent: *\nAllow: /\n", 200, {
            "Content-Type": "text/plain; charset=utf-8",
        })


@main_bp.route("/sitemap.xml")
def sitemap_xml():
    try:
        return send_from_directory(
            current_app.static_folder,
            "sitemap.xml",
            mimetype="application/xml",
        )
    except Exception:
        # Minimal fallback so crawlers still get a valid document.
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
    """Prevent 404 noise in server logs — the browser always asks for this."""
    try:
        return send_from_directory(
            current_app.static_folder, "favicon.ico",
            mimetype="image/vnd.microsoft.icon",
        )
    except Exception:
        # If the file is missing, return an empty 204 rather than a 404.
        return ("", 204)


# ---------------------------------------------------------------------------
# Friendly fallbacks — common typos that shouldn't dump users on a 404
# ---------------------------------------------------------------------------

@main_bp.route("/dashboard/", strict_slashes=False, endpoint="dashboard_slash")
def _dashboard_slash():
    """Someone typed /dashboard/ with a trailing slash — normalize."""
    return redirect(url_for("main.redirect_dashboard"))


@main_bp.route("/auth/login/", strict_slashes=False, endpoint="login_slash")
def _login_slash():
    return redirect(url_for("auth.login"))


@main_bp.route("/auth/signup/", strict_slashes=False, endpoint="signup_slash")
def _signup_slash():
    return redirect(url_for("auth.signup"))