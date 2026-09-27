from datetime import datetime
from flask import (
    Blueprint, render_template, redirect, url_for, request, flash,
)
from flask_login import current_user

from models import find_tenant_by_id
from app.services import tenant_service

main_bp = Blueprint("main", __name__)


# ---------------------------------------------------------------------------
# Landing
# ---------------------------------------------------------------------------

@main_bp.route("/")
def landing():
    return render_template("landing.html")


# ---------------------------------------------------------------------------
# Role-based redirect (used by login & landing CTA)
# ---------------------------------------------------------------------------

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
# Subscription locked
# ---------------------------------------------------------------------------

@main_bp.route("/subscription/locked")
def subscription_locked():
    tenant = None
    if current_user.is_authenticated and current_user.tenant_id:
        tenant = find_tenant_by_id(current_user.tenant_id)
    return render_template("errors/subscription_locked.html", tenant=tenant)


# ---------------------------------------------------------------------------
# Owner renew (from lock page or subscription page)
# ---------------------------------------------------------------------------

@main_bp.route("/subscription/renew", methods=["POST"])
def renew_subscription():
    if not current_user.is_authenticated:
        return redirect(url_for("auth.login"))
    if current_user.role != "owner":
        flash("Only the owner can renew the subscription.", "warning")
        return redirect(url_for("main.subscription_locked"))

    tenant = find_tenant_by_id(current_user.tenant_id)
    if not tenant:
        flash("Pharmacy record not found.", "danger")
        return redirect(url_for("auth.logout"))

    # Route the owner to the payment page, where they can complete Paystack checkout.
    return redirect(url_for("auth.payment"))


# ---------------------------------------------------------------------------
# Healthcheck (optional but useful for load balancers)
# ---------------------------------------------------------------------------

@main_bp.route("/healthz")
def healthz():
    from extensions import mongo
    try:
        mongo.db.command("ping")
        return {"status": "ok", "time": datetime.utcnow().isoformat()}, 200
    except Exception as e:
        return {"status": "degraded", "error": str(e)}, 503


# ---------------------------------------------------------------------------
# robots.txt and sitemap.xml (served from static)
# ---------------------------------------------------------------------------

@main_bp.route("/robots.txt")
def robots_txt():
    from flask import send_from_directory, current_app
    return send_from_directory(current_app.static_folder, "robots.txt")


@main_bp.route("/sitemap.xml")
def sitemap_xml():
    from flask import send_from_directory, current_app
    return send_from_directory(
        current_app.static_folder, "sitemap.xml", mimetype="application/xml"
    )