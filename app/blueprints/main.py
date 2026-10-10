from datetime import datetime
from flask import (
    Blueprint, render_template, redirect, url_for, request, flash,
    jsonify, abort, current_app, send_from_directory,
)
from flask_login import current_user, login_required

from models import find_tenant_by_id
from app.services import tenant_service, auth_service
from extensions import mongo


main_bp = Blueprint("main", __name__)


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

    if requested and requested in tiers:
        if requested != tenant.tier:
            # Record intent; do not modify `tier` yet
            tenant_service.set_pending_tier(tenant._id, requested)
            flash(
                f"Ready to switch to {tiers[requested]['label']}. "
                "Complete payment to activate the new plan.",
                "info",
            )
        else:
            # Same tier — just a renewal, clear any stale pending change
            tenant_service.clear_pending_tier(tenant._id)

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


@main_bp.route("/api/session-token")
@login_required
def session_token():
    tokens = auth_service.issue_tokens(current_user)
    return jsonify({"access": tokens["access"], "expires_in": tokens["expires_in"]})


@main_bp.route("/r/<receipt_no>")
def verify_receipt_page(receipt_no):
    sale = mongo.db.sales.find_one({"receipt_no": receipt_no})
    if not sale:
        abort(404)
    return render_template("receipt_verify.html", sale=sale)


@main_bp.route("/healthz")
def healthz():
    try:
        mongo.db.command("ping")
        return {"status": "ok", "time": datetime.utcnow().isoformat()}, 200
    except Exception as e:
        return {"status": "degraded", "error": str(e)}, 503


@main_bp.route("/robots.txt")
def robots_txt():
    return send_from_directory(current_app.static_folder, "robots.txt")


@main_bp.route("/sitemap.xml")
def sitemap_xml():
    return send_from_directory(
        current_app.static_folder, "sitemap.xml", mimetype="application/xml"
    )