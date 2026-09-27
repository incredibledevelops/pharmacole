from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, abort,
)
from flask_login import login_required, current_user

from decorators import role_required, subscription_required
from models import find_tenant_by_id
from app.services import (
    inventory_service, prescription_service, supplier_service,
)
from utils import to_int

pharmacist_bp = Blueprint("pharmacist", __name__, url_prefix="/pharmacist")


@pharmacist_bp.before_request
@login_required
@role_required("pharmacist")
@subscription_required
def _guard():
    return None


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@pharmacist_bp.route("/dashboard")
def dashboard():
    tenant = find_tenant_by_id(current_user.tenant_id)
    total_skus = inventory_service.count_for_tenant(current_user.tenant_id)
    low_stock = inventory_service.low_stock(current_user.tenant_id, limit=20)
    expiring = inventory_service.expiring_within(current_user.tenant_id, days=30, limit=20)
    pending_rx = prescription_service.count_pending(current_user.tenant_id)

    return render_template(
        "pharmacist/dashboard.html",
        tenant=tenant,
        total_skus=total_skus,
        low_stock=low_stock,
        expiring=expiring,
        pending_rx=pending_rx,
    )


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------

@pharmacist_bp.route("/inventory")
def inventory():
    tenant = find_tenant_by_id(current_user.tenant_id)
    items = inventory_service.list_for_tenant(current_user.tenant_id, limit=2000)
    return render_template("pharmacist/inventory.html", tenant=tenant, items=items)


@pharmacist_bp.route("/inventory/add", methods=["GET", "POST"])
def add_drug():
    tenant = find_tenant_by_id(current_user.tenant_id)

    if request.method == "POST":
        data = {
            "name": request.form.get("name"),
            "sku": request.form.get("sku"),
            "category": request.form.get("category"),
            "dosage_form": request.form.get("dosage_form"),
            "pack_size": request.form.get("pack_size"),
            "cost_price": request.form.get("cost_price"),
            "selling_price": request.form.get("selling_price"),
            "tax_rate": request.form.get("tax_rate"),
            "quantity": request.form.get("quantity"),
            "min_threshold": request.form.get("min_threshold"),
            "batch_number": request.form.get("batch_number"),
            "expiry_date": request.form.get("expiry_date"),
            "supplier": request.form.get("supplier"),
            "description": request.form.get("description"),
        }
        try:
            inventory_service.create_item(current_user.tenant_id, data)
            flash("Drug added to inventory.", "success")
            return redirect(url_for("pharmacist.inventory"))
        except ValueError as e:
            flash(str(e), "danger")
        except Exception:
            flash("Could not save the drug. Please check the fields.", "danger")

    suppliers = supplier_service.list_for_tenant(current_user.tenant_id)
    return render_template(
        "pharmacist/add_drug.html",
        tenant=tenant,
        suppliers=suppliers,
    )


@pharmacist_bp.route("/inventory/<item_id>/adjust", methods=["POST"])
def adjust_stock(item_id):
    delta = request.form.get("delta")
    reason = request.form.get("reason")
    try:
        inventory_service.adjust_stock(
            tenant_id=current_user.tenant_id,
            item_id=item_id,
            delta=delta,
            reason=reason,
            actor_id=current_user._id,
        )
        flash("Stock adjusted.", "success")
    except ValueError as e:
        flash(str(e), "danger")
    return redirect(url_for("pharmacist.inventory"))


# ---------------------------------------------------------------------------
# Expiry tracker
# ---------------------------------------------------------------------------

@pharmacist_bp.route("/expiry")
def expiry():
    tenant = find_tenant_by_id(current_user.tenant_id)

    buckets = {
        "30": inventory_service.expiring_within(current_user.tenant_id, days=30),
        "60": [],
        "90": [],
    }
    # 31-60
    within_60 = inventory_service.expiring_within(current_user.tenant_id, days=60)
    seen_30 = {str(i["_id"]) for i in buckets["30"]}
    buckets["60"] = [i for i in within_60 if str(i["_id"]) not in seen_30]
    # 61-90
    within_90 = inventory_service.expiring_within(current_user.tenant_id, days=90)
    seen_60 = seen_30 | {str(i["_id"]) for i in buckets["60"]}
    buckets["90"] = [i for i in within_90 if str(i["_id"]) not in seen_60]

    return render_template("pharmacist/expiry.html", tenant=tenant, buckets=buckets)


# ---------------------------------------------------------------------------
# Prescriptions
# ---------------------------------------------------------------------------

@pharmacist_bp.route("/prescriptions")
def prescription():
    tenant = find_tenant_by_id(current_user.tenant_id)
    items = prescription_service.list_for_tenant(current_user.tenant_id, limit=200)
    return render_template("pharmacist/prescription.html", tenant=tenant, prescriptions=items)


@pharmacist_bp.route("/prescriptions/<rx_id>/status", methods=["POST"])
def set_prescription_status(rx_id):
    status = (request.form.get("status") or "").strip()
    ok = prescription_service.set_status(current_user.tenant_id, rx_id, status)
    flash("Prescription updated." if ok else "Could not update.", "success" if ok else "danger")
    return redirect(url_for("pharmacist.prescription"))