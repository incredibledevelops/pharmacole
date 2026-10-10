from datetime import datetime
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, Response, current_app, abort,
)
from flask_login import login_required, current_user

from decorators import role_required, subscription_required, feature_required
from models import find_tenant_by_id
from utils import oid
from app.services import (
    user_service, inventory_service, sales_service,
    supplier_service, payments_service, tenant_service,
    branch_service, audit_service, entitlement_service,
)

owner_bp = Blueprint("owner", __name__, url_prefix="/owner")


@owner_bp.before_request
@login_required
@role_required("owner")
@subscription_required
def _guard():
    return None


@owner_bp.route("/dashboard")
def dashboard():
    tenant = find_tenant_by_id(current_user.tenant_id)
    employees = user_service.list_for_tenant(current_user.tenant_id)
    low_stock = inventory_service.low_stock(current_user.tenant_id, limit=10)
    expiring = inventory_service.expiring_within(current_user.tenant_id, limit=10)
    recent_sales = sales_service.recent_sales(current_user.tenant_id, limit=10)
    revenue_today = sales_service.revenue_today(current_user.tenant_id)

    tier = entitlement_service.limits_for(current_user.tenant_id)
    usage = {
        "branches": entitlement_service.count_active_branches(current_user.tenant_id),
        "users": entitlement_service.count_active_users(current_user.tenant_id),
        "branch_limit": tier.get("branches", 1),
        "user_limit": tier.get("users", -1),
        "tier_label": tier.get("label", "Pro"),
    }

    return render_template(
        "owner/dashboard.html",
        tenant=tenant,
        employees=employees,
        low_stock=low_stock,
        expiring=expiring,
        recent_sales=recent_sales,
        total_sales_today=revenue_today,
        tier_usage=usage,
    )


@owner_bp.route("/employees")
def employees():
    tenant = find_tenant_by_id(current_user.tenant_id)
    staff = user_service.list_for_tenant(current_user.tenant_id)
    tier = entitlement_service.limits_for(current_user.tenant_id)
    user_count = entitlement_service.count_active_users(current_user.tenant_id)
    user_limit = tier.get("users", -1)
    can_add = (user_limit == -1) or (user_count < user_limit)

    return render_template(
        "owner/employees.html",
        tenant=tenant,
        employees=staff,
        user_count=user_count,
        user_limit=user_limit,
        can_add_user=can_add,
        tier_label=tier.get("label", "Pro"),
    )


@owner_bp.route("/employees/add", methods=["POST"])
def add_employee():
    full_name = (request.form.get("full_name") or "").strip()
    email = (request.form.get("email") or "").lower().strip()
    role = (request.form.get("role") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    password = request.form.get("password") or ""

    if role not in ("pharmacist", "cashier"):
        flash("Invalid role.", "danger")
        return redirect(url_for("owner.employees"))

    if not full_name or not email or len(password) < 6:
        flash("Name, email and password (min 6 chars) are required.", "danger")
        return redirect(url_for("owner.employees"))

    try:
        user_service.create_user(
            email=email,
            password=password,
            full_name=full_name,
            role=role,
            tenant_id=current_user.tenant_id,
            phone=phone,
        )
        audit_service.log("employee.add", meta={"email": email, "role": role})
        flash(f"{full_name} added.", "success")
    except ValueError as e:
        flash(str(e), "danger")

    return redirect(url_for("owner.employees"))


@owner_bp.route("/employees/<user_id>/toggle", methods=["POST"])
def toggle_employee(user_id):
    target = user_service.get_by_id(user_id)
    if not target or str(target.tenant_id) != str(current_user.tenant_id):
        abort(404)

    if target.role == "pharmacist" and target.is_active:
        active_pharmacists = [
            u for u in user_service.list_by_role(current_user.tenant_id, "pharmacist")
            if u.is_active and u._id != target._id
        ]
        if not active_pharmacists:
            flash("You cannot deactivate the last active pharmacist.", "danger")
            return redirect(url_for("owner.employees"))

    try:
        new_state = user_service.toggle_active(user_id)
    except ValueError as e:
        flash(str(e), "danger")
        return redirect(url_for("owner.employees"))

    audit_service.log("employee.toggle",
                      target=user_id, meta={"active": new_state})
    flash(
        f"{target.full_name} {'activated' if new_state else 'deactivated'}.",
        "success" if new_state else "warning",
    )
    return redirect(url_for("owner.employees"))


@owner_bp.route("/inventory")
def inventory():
    tenant = find_tenant_by_id(current_user.tenant_id)
    items = inventory_service.list_for_tenant(current_user.tenant_id, limit=2000)
    return render_template("owner/inventory.html", tenant=tenant, items=items)


@owner_bp.route("/reports")
@feature_required("reports")
def reports():
    tenant = find_tenant_by_id(current_user.tenant_id)
    sales = sales_service.list_for_tenant(current_user.tenant_id, limit=1000)
    summary = sales_service.summary_for_tenant(current_user.tenant_id)

    consolidated = None
    if entitlement_service.tenant_has_feature(current_user.tenant_id, "consolidated_reports"):
        consolidated = sales_service.consolidated_summary(current_user.tenant_id)

    return render_template(
        "owner/reports.html",
        tenant=tenant,
        sales=sales,
        summary=summary,
        consolidated=consolidated,
    )


@owner_bp.route("/reports/export.csv")
@feature_required("reports")
def export_csv():
    sales = sales_service.list_for_tenant(current_user.tenant_id, limit=10000)

    def rows():
        yield "receipt_no,timestamp,cashier,items_count,payment_method,subtotal,vat,total\n"
        for s in sales:
            ts = s.get("timestamp")
            ts_str = ts.strftime("%Y-%m-%d %H:%M") if ts else ""
            yield (
                f"{s.get('receipt_no','')},"
                f"{ts_str},"
                f"\"{s.get('cashier_name','')}\","
                f"{len(s.get('items', []))},"
                f"{s.get('payment_method','')},"
                f"{s.get('subtotal',0):.2f},"
                f"{s.get('vat',0):.2f},"
                f"{s.get('total_amount',0):.2f}\n"
            )

    filename = f"sales-{datetime.utcnow():%Y%m%d-%H%M}.csv"
    return Response(
        rows(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@owner_bp.route("/suppliers")
@feature_required("suppliers")
def suppliers():
    tenant = find_tenant_by_id(current_user.tenant_id)
    items = supplier_service.list_for_tenant(current_user.tenant_id)
    return render_template("owner/suppliers.html", tenant=tenant, suppliers=items)


@owner_bp.route("/suppliers/add", methods=["POST"])
@feature_required("suppliers")
def add_supplier():
    name = (request.form.get("name") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    email = (request.form.get("email") or "").strip()
    address = (request.form.get("address") or "").strip()

    if not name:
        flash("Supplier name is required.", "danger")
        return redirect(url_for("owner.suppliers"))

    try:
        supplier_service.create_supplier(
            tenant_id=current_user.tenant_id,
            name=name, phone=phone, email=email, address=address,
        )
        audit_service.log("supplier.add", meta={"name": name})
        flash("Supplier saved.", "success")
    except ValueError as e:
        flash(str(e), "danger")

    return redirect(url_for("owner.suppliers"))


@owner_bp.route("/branches")
@feature_required("multi_branch")
def branches():
    tenant = find_tenant_by_id(current_user.tenant_id)
    items = branch_service.list_for_tenant(current_user.tenant_id, active_only=False)
    tier = entitlement_service.limits_for(current_user.tenant_id)
    branch_limit = tier.get("branches", 1)
    can_add = (branch_limit == -1) or (len(items) < branch_limit)

    return render_template(
        "owner/branches.html",
        tenant=tenant,
        branches=items,
        branch_limit=branch_limit,
        can_add_branch=can_add,
        tier_label=tier.get("label", "Business"),
    )


@owner_bp.route("/branches/add", methods=["POST"])
@feature_required("multi_branch")
def add_branch():
    name = (request.form.get("name") or "").strip()
    address = (request.form.get("address") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    try:
        bid = branch_service.create_branch(
            current_user.tenant_id, name=name, address=address, phone=phone,
        )
        audit_service.log("branch.create", target=str(bid), meta={"name": name})
        flash(f"Branch '{name}' created.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("owner.branches"))


@owner_bp.route("/branches/<branch_id>/default", methods=["POST"])
@feature_required("multi_branch")
def make_branch_default(branch_id):
    ok = branch_service.set_default(current_user.tenant_id, branch_id)
    if ok:
        audit_service.log("branch.set_default", target=branch_id)
        flash("Default branch updated.", "success")
    else:
        flash("Could not update branch.", "danger")
    return redirect(url_for("owner.branches"))


@owner_bp.route("/branches/<branch_id>/toggle", methods=["POST"])
@feature_required("multi_branch")
def toggle_branch(branch_id):
    b = branch_service.get(current_user.tenant_id, branch_id)
    if not b:
        abort(404)
    branch_service.update(current_user.tenant_id, branch_id, is_active=not b.is_active)
    audit_service.log("branch.toggle",
                      target=branch_id, meta={"active": not b.is_active})
    flash(f"Branch {'activated' if not b.is_active else 'deactivated'}.", "success")
    return redirect(url_for("owner.branches"))


@owner_bp.route("/audit")
@feature_required("audit_log")
def audit():
    tenant = find_tenant_by_id(current_user.tenant_id)
    return render_template("owner/audit.html", tenant=tenant)


@owner_bp.route("/subscription")
def subscription():
    tenant = find_tenant_by_id(current_user.tenant_id)
    payments = payments_service.list_for_tenant(current_user.tenant_id, limit=50)
    tiers = current_app.config["PRICING_TIERS"]
    tier_order = current_app.config["TIER_ORDER"]
    current_tier = tenant.tier if tenant and tenant.tier in tiers else "pro"
    pending_tier = tenant.pending_tier if tenant and tenant.pending_tier in tiers else None
    return render_template(
        "owner/subscription.html",
        tenant=tenant,
        payments=payments,
        tiers=tiers,
        tier_order=tier_order,
        current_tier=current_tier,
        pending_tier=pending_tier,
    )


@owner_bp.route("/subscription/renew", methods=["POST"])
def renew():
    return redirect(url_for("auth.payment"))