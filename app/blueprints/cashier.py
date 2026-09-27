from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort,
)
from flask_login import login_required, current_user

from decorators import role_required, subscription_required
from models import find_tenant_by_id
from extensions import limiter
from app.services import inventory_service, sales_service, held_order_service

cashier_bp = Blueprint("cashier", __name__, url_prefix="/cashier")


@cashier_bp.before_request
@login_required
@role_required("cashier", "owner")  # Owners can use POS too
@subscription_required
def _guard():
    return None


# ---------------------------------------------------------------------------
# POS
# ---------------------------------------------------------------------------

@cashier_bp.route("/pos")
def pos():
    tenant = find_tenant_by_id(current_user.tenant_id)
    products = inventory_service.list_for_tenant(current_user.tenant_id, limit=2000)
    # keep only in-stock products for the grid
    products = [p for p in products if int(p.get("quantity", 0)) > 0]

    today_total = sales_service.revenue_today(current_user.tenant_id)

    return render_template(
        "cashier/pos.html",
        tenant=tenant,
        products=products,
        today_total=today_total,
    )


# ---------------------------------------------------------------------------
# Checkout (JSON API)
# ---------------------------------------------------------------------------

@cashier_bp.route("/checkout", methods=["POST"])
@limiter.limit("300 per hour")
def checkout():
    payload = request.get_json(silent=True) or {}
    items = payload.get("items") or []
    method = (payload.get("payment_method") or "").strip().lower()

    if not items:
        return jsonify({"error": "Cart is empty."}), 400
    if method not in ("cash", "card", "momo"):
        return jsonify({"error": "Invalid payment method."}), 400

    try:
        receipt = sales_service.record_sale(
            tenant_id=current_user.tenant_id,
            cashier=current_user,
            items=items,
            payment_method=method,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        return jsonify({"error": "Checkout failed. Please try again."}), 500

    return jsonify(receipt)


# ---------------------------------------------------------------------------
# Shift report
# ---------------------------------------------------------------------------

@cashier_bp.route("/shift")
def shift_report():
    tenant = find_tenant_by_id(current_user.tenant_id)
    sales = sales_service.list_for_cashier_today(current_user.tenant_id, current_user._id)
    total = sum(float(s.get("total_amount", 0)) for s in sales)
    return render_template(
        "cashier/shift_report.html",
        tenant=tenant,
        sales=sales,
        total=total,
    )


# ---------------------------------------------------------------------------
# Held orders
# ---------------------------------------------------------------------------

@cashier_bp.route("/held")
def held_orders():
    tenant = find_tenant_by_id(current_user.tenant_id)
    held = held_order_service.list_for_tenant(current_user.tenant_id)
    return render_template("cashier/held_orders.html", tenant=tenant, held=held)


@cashier_bp.route("/held", methods=["POST"])
def hold_order():
    payload = request.get_json(silent=True) or {}
    items = payload.get("items") or []
    label = payload.get("label")
    try:
        held_id = held_order_service.hold(
            tenant_id=current_user.tenant_id,
            cashier=current_user,
            items=items,
            label=label,
        )
        return jsonify({"ok": True, "id": str(held_id)})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@cashier_bp.route("/held/<held_id>/resume")
def resume_held(held_id):
    held = held_order_service.get(current_user.tenant_id, held_id)
    if not held:
        abort(404)
    held_order_service.delete(current_user.tenant_id, held_id)

    tenant = find_tenant_by_id(current_user.tenant_id)
    products = inventory_service.list_for_tenant(current_user.tenant_id, limit=2000)
    products = [p for p in products if int(p.get("quantity", 0)) > 0]
    today_total = sales_service.revenue_today(current_user.tenant_id)

    # Rehydrate cart into template
    cart = []
    for line in held.get("items", []):
        cart.append({
            "id": str(line.get("inventory_id")),
            "name": line.get("name"),
            "price": float(line.get("price", 0)),
            "qty": int(line.get("qty", 0)),
        })

    return render_template(
        "cashier/pos.html",
        tenant=tenant,
        products=products,
        today_total=today_total,
        initial_cart=cart,
    )


@cashier_bp.route("/held/<held_id>/delete", methods=["POST"])
def delete_held(held_id):
    ok = held_order_service.delete(current_user.tenant_id, held_id)
    flash("Held order removed." if ok else "Could not remove.", "success" if ok else "danger")
    return redirect(url_for("cashier.held_orders"))