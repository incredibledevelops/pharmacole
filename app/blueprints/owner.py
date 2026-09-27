from datetime import datetime
from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, Response, current_app, abort,
)
from flask_login import login_required, current_user

from decorators import role_required, subscription_required
from models import find_tenant_by_id
from utils import to_float, to_int, oid
from app.services import (
    user_service, inventory_service, sales_service,
    supplier_service, payments_service, tenant_service,
)

owner_bp = Blueprint("owner", __name__, url_prefix="/owner")


@owner_bp.before_request
@login_required
@role_required("owner")
@subscription_required
def _guard():
    """Applies to every route in this blueprint."""
    return None


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@owner_bp.route("/dashboard")
def dashboard():
    tenant = find_tenant_by_id(current_user.tenant_id)
    employees = user_service.list_for_tenant(current_user.tenant_id)
    low_stock = inventory_service.low_stock(current_user.tenant_id, limit=10)
    expiring = inventory_service.expiring_within(current_user.tenant_id, days=30, limit=10)
    recent_sales = sales_service.recent_sales(current_user.tenant_id, limit=10)
    revenue_today = sales_service.revenue_today(current_user.tenant_id)

    return render_template(
        "owner/dashboard.html",
        tenant=tenant,
        employees=employees,
        low_stock=low_stock,
        expiring=expiring,
        recent_sales=recent_sales,
        total_sales_today=revenue_today,
    )


# ---------------------------------------------------------------------------
# Employees
# ---------------------------------------------------------------------------

@owner_bp.route("/employees")
def employees():
    tenant = find_tenant_by_id(current_user.tenant_id)
    staff = user_service.list_for_tenant(current_user.tenant_id)
    return render_template("owner/employees.html", tenant=tenant, employees=staff)


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
        flash(f"{full_name} added.", "success")
    except ValueError as e:
        flash(str(e), "danger")

    return redirect(url_for("owner.employees"))


@owner_bp.route("/employees/<user_id>/toggle", methods=["POST"])
def toggle_employee(user_id):
    target = user_service.get_by_id(user_id)
    if not target or str(target.tenant_id) != str(current_user.tenant_id):
        abort(404)

    # Prevent deactivating the last active pharmacist
    if target.role == "pharmacist" and target.is_active:
        active_pharmacists = [
            u for u in user_service.list_by_role(current_user.tenant_id, "pharmacist")
            if u.is_active and u._id != target._id
        ]
        if not active_pharmacists:
            flash("You cannot deactivate the last active pharmacist.", "danger")
            return redirect(url_for("owner.employees"))

    new_state = user_service.toggle_active(user_id)
    flash(
        f"{target.full_name} {'activated' if new_state else 'deactivated'}.",
        "success" if new_state else "warning",
    )
    return redirect(url_for("owner.employees"))


# ---------------------------------------------------------------------------
# Inventory (read-only view for owner)
# ---------------------------------------------------------------------------

@owner_bp.route("/inventory")
def inventory():
    tenant = find_tenant_by_id(current_user.tenant_id)
    items = inventory_service.list_for_tenant(current_user.tenant_id, limit=2000)
    return render_template("owner/inventory.html", tenant=tenant, items=items)


# ---------------------------------------------------------------------------
# Sales & Reports
# ---------------------------------------------------------------------------

@owner_bp.route("/reports")
def reports():
    tenant = find_tenant_by_id(current_user.tenant_id)
    sales = sales_service.list_for_tenant(current_user.tenant_id, limit=1000)
    summary = sales_service.summary_for_tenant(current_user.tenant_id)
    return render_template(
        "owner/reports.html",
        tenant=tenant,
        sales=sales,
        summary=summary,
    )


@owner_bp.route("/reports/export.csv")
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


# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------

@owner_bp.route("/suppliers")
def suppliers():
    tenant = find_tenant_by_id(current_user.tenant_id)
    items = supplier_service.list_for_tenant(current_user.tenant_id)
    return render_template("owner/suppliers.html", tenant=tenant, suppliers=items)


@owner_bp.route("/suppliers/add", methods=["POST"])
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
            name=name,
            phone=phone,
            email=email,
            address=address,
        )
        flash("Supplier saved.", "success")
    except ValueError as e:
        flash(str(e), "danger")

    return redirect(url_for("owner.suppliers"))


# ---------------------------------------------------------------------------
# Subscription
# ---------------------------------------------------------------------------

@owner_bp.route("/subscription")
def subscription():
    tenant = find_tenant_by_id(current_user.tenant_id)
    payments = payments_service.list_for_tenant(current_user.tenant_id, limit=50)
    return render_template(
        "owner/subscription.html",
        tenant=tenant,
        payments=payments,
    )


@owner_bp.route("/subscription/renew", methods=["POST"])
def renew():
    return redirect(url_for("auth.payment"))