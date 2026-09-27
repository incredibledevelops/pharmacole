from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, abort, jsonify,
)
from flask_login import login_required, current_user

from decorators import role_required
from models import find_tenant_by_id, find_user_by_email, find_user_by_id
from utils import oid
from app.services import (
    tenant_service, user_service, payments_service,
    dispute_service, sales_service, inventory_service,
)

super_admin_bp = Blueprint("super_admin", __name__, url_prefix="/super-admin")


@super_admin_bp.before_request
@login_required
@role_required("super_admin")
def _guard():
    return None


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@super_admin_bp.route("/dashboard")
def dashboard():
    stats = tenant_service.stats()
    mrr = tenant_service.monthly_recurring_revenue()
    recent_tenants = tenant_service.list_all(skip=0, limit=5)
    recent_payments = payments_service.recent(limit=5)

    return render_template(
        "super-admin/dashboard.html",
        total_tenants=stats["total"],
        active=stats["active"],
        expired=stats["expired"] + stats["pending"],
        mrr=mrr,
        recent_tenants=recent_tenants,
        recent_payments=recent_payments,
    )


# ---------------------------------------------------------------------------
# Tenants
# ---------------------------------------------------------------------------

@super_admin_bp.route("/tenants")
def tenants():
    page = max(1, int(request.args.get("page", 1)))
    per_page = 50
    skip = (page - 1) * per_page
    items = tenant_service.list_all(skip=skip, limit=per_page)
    total = tenant_service.count_all()
    return render_template(
        "super-admin/tenants.html",
        tenants=items,
        page=page,
        per_page=per_page,
        total=total,
        has_next=(skip + per_page) < total,
    )


@super_admin_bp.route("/tenants/<tenant_id>")
def tenant_detail(tenant_id):
    tenant = find_tenant_by_id(tenant_id)
    if not tenant:
        abort(404)
    users = user_service.list_for_tenant(tenant._id)
    payments = payments_service.list_for_tenant(tenant._id, limit=50)
    return render_template(
        "super-admin/tenant_detail.html",
        tenant=tenant,
        users=users,
        payments=payments,
    )


@super_admin_bp.route("/tenants/<tenant_id>/activate", methods=["POST"])
def activate_tenant(tenant_id):
    days = int(request.form.get("days", 30))
    ok = tenant_service.activate(tenant_id, days=days)
    flash(f"Tenant activated for {days} days." if ok else "Could not activate.", "success" if ok else "danger")
    return redirect(url_for("super_admin.tenant_detail", tenant_id=tenant_id))


@super_admin_bp.route("/tenants/<tenant_id>/expire", methods=["POST"])
def expire_tenant(tenant_id):
    tenant_service.mark_expired(tenant_id)
    flash("Tenant marked as expired.", "warning")
    return redirect(url_for("super_admin.tenant_detail", tenant_id=tenant_id))


# ---------------------------------------------------------------------------
# Billing
# ---------------------------------------------------------------------------

@super_admin_bp.route("/billing")
def billing():
    page = max(1, int(request.args.get("page", 1)))
    per_page = 50
    skip = (page - 1) * per_page
    items = payments_service.list_all(skip=skip, limit=per_page)

    # Attach tenant code for display
    enriched = []
    for p in items:
        tenant = find_tenant_by_id(p.get("tenant_id"))
        p["tenant_code"] = tenant.tenant_code if tenant else "—"
        enriched.append(p)

    return render_template(
        "super-admin/billing.html",
        payments=enriched,
        page=page,
    )


# ---------------------------------------------------------------------------
# Disputes
# ---------------------------------------------------------------------------

@super_admin_bp.route("/disputes")
def disputes():
    items = dispute_service.list_all(limit=200)
    # Attach tenant_code if missing
    for d in items:
        if not d.get("tenant_code") and d.get("tenant_id"):
            tenant = find_tenant_by_id(d["tenant_id"])
            d["tenant_code"] = tenant.tenant_code if tenant else "—"
    return render_template("super-admin/disputes.html", disputes=items)


@super_admin_bp.route("/disputes/<dispute_id>/status", methods=["POST"])
def set_dispute_status(dispute_id):
    status = (request.form.get("status") or "").strip()
    ok = dispute_service.set_status(dispute_id, status)
    flash("Dispute updated." if ok else "Could not update.", "success" if ok else "danger")
    return redirect(url_for("super_admin.disputes"))