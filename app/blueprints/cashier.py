from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort,
)
from flask_login import login_required, current_user

from decorators import role_required, subscription_required
from models import find_tenant_by_id
from extensions import limiter
from utils import oid
from app.services import inventory_service, sales_service, held_order_service
from app.services.inventory_service import _BRANCH_ANY

cashier_bp = Blueprint("cashier", __name__, url_prefix="/cashier")


def _branch_for(user):
    bid = oid(getattr(user, "branch_id", None))
    return bid if bid else _BRANCH_ANY


def _branch_id_for(user):
    return oid(getattr(user, "branch_id", None))


def _recent_items_for(tenant_id, branch_id, limit=8):
    """
    Return the most recently sold inventory items (by latest sale)
    so the POS can show a 'Recently sold' strip. Fall back to nothing
    if the sale's inventory item was deleted.
    """
    try:
        from extensions import mongo
        branch = branch_id if branch_id else None
        query = {"tenant_id": oid(tenant_id)}
        if branch is not None:
            query["branch_id"] = branch
        recent = mongo.db.sales.find(query).sort("timestamp", -1).limit(20)
        seen = set()
        out = []
        for s in recent:
            for line in s.get("items", []):
                iid = line.get("inventory_id")
                if not iid or str(iid) in seen:
                    continue
                seen.add(str(iid))
                item = mongo.db.inventory.find_one({"_id": iid, "tenant_id": oid(tenant_id)})
                if item and int(item.get("quantity", 0)) > 0:
                    out.append(item)
                if len(out) >= limit:
                    return out
        return out
    except Exception:
        return []


@cashier_bp.before_request
@login_required
@role_required("cashier", "owner")
@subscription_required
def _guard():
    return None


@cashier_bp.route("/pos")
def pos():
    tenant = find_tenant_by_id(current_user.tenant_id)
    branch = _branch_for(current_user)
    branch_id = _branch_id_for(current_user)
    products = inventory_service.list_for_tenant(
        current_user.tenant_id, limit=2000, branch_id=branch,
    )
    products = [p for p in products if int(p.get("quantity", 0)) > 0]
    today_total = sales_service.revenue_today(
        current_user.tenant_id, branch_id=branch_id,
    )
    recent_items = _recent_items_for(current_user.tenant_id, branch_id)

    return render_template(
        "cashier/pos.html",
        tenant=tenant,
        products=products,
        today_total=today_total,
        recent_items=recent_items,
    )


@cashier_bp.route("/checkout", methods=["POST"])
@limiter.limit("300 per hour")
def checkout():
    payload = request.get_json(silent=True) or {}
    items = payload.get("items") or []
    method = (payload.get("payment_method") or "").strip().lower()
    client_uuid = payload.get("client_uuid")
    customer_name = payload.get("customer_name")
    discount = payload.get("discount", 0.0)

    if not items:
        return jsonify({"error": "Cart is empty."}), 400
    if method not in ("cash", "card", "momo"):
        return jsonify({"error": "Invalid payment method."}), 400

    user_branch = _branch_id_for(current_user)
    payload_branch = payload.get("branch_id")
    if user_branch is not None:
        branch_id = user_branch
    else:
        branch_id = oid(payload_branch) if payload_branch else None

    try:
        receipt = sales_service.record_sale(
            tenant_id=current_user.tenant_id,
            cashier=current_user,
            items=items,
            payment_method=method,
            branch_id=branch_id,
            client_uuid=client_uuid,
            customer_name=customer_name,
            discount=discount,
        )
    except sales_service.IdempotentReplay as replay:
        return jsonify(sales_service._sale_to_dict(replay.existing)), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        return jsonify({"error": "Checkout failed. Please try again."}), 500

    return jsonify(receipt)


@cashier_bp.route("/shift")
def shift_report():
    tenant = find_tenant_by_id(current_user.tenant_id)
    sales = sales_service.list_for_cashier_today(
        current_user.tenant_id,
        current_user._id,
        branch_id=_branch_id_for(current_user),
    )
    total = sum(float(s.get("total_amount", 0)) for s in sales)

    # First sale of the day = shift start. Kept in UTC because sales
    # timestamps are stored in UTC.
    shift_started = sales[-1]["timestamp"] if sales else None

    return render_template(
        "cashier/shift_report.html",
        tenant=tenant,
        sales=sales,
        total=total,
        shift_started=shift_started,
    )


@cashier_bp.route("/held")
def held_orders():
    tenant = find_tenant_by_id(current_user.tenant_id)
    branch = _branch_for(current_user)
    held = held_order_service.list_for_tenant(
        current_user.tenant_id, branch_id=branch,
    )
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
            branch_id=_branch_id_for(current_user),
        )
        return jsonify({"ok": True, "id": str(held_id)})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@cashier_bp.route("/held/<held_id>/resume")
def resume_held(held_id):
    held = held_order_service.get(current_user.tenant_id, held_id)
    if not held:
        abort(404)

    user_branch = _branch_id_for(current_user)
    if user_branch is not None and held.get("branch_id") != user_branch:
        abort(403)

    held_order_service.delete(current_user.tenant_id, held_id)

    tenant = find_tenant_by_id(current_user.tenant_id)
    branch = _branch_for(current_user)
    branch_id = _branch_id_for(current_user)
    products = inventory_service.list_for_tenant(
        current_user.tenant_id, limit=2000, branch_id=branch,
    )
    products = [p for p in products if int(p.get("quantity", 0)) > 0]
    today_total = sales_service.revenue_today(
        current_user.tenant_id, branch_id=branch_id,
    )
    recent_items = _recent_items_for(current_user.tenant_id, branch_id)

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
        tenant=tenant, products=products,
        today_total=today_total, initial_cart=cart,
        recent_items=recent_items,
    )


@cashier_bp.route("/held/<held_id>/delete", methods=["POST"])
def delete_held(held_id):
    held = held_order_service.get(current_user.tenant_id, held_id)
    if not held:
        flash("Held order not found.", "danger")
        return redirect(url_for("cashier.held_orders"))

    user_branch = _branch_id_for(current_user)
    if user_branch is not None and held.get("branch_id") != user_branch:
        abort(403)

    ok = held_order_service.delete(current_user.tenant_id, held_id)
    flash("Held order removed." if ok else "Could not remove.",
          "success" if ok else "danger")
    return redirect(url_for("cashier.held_orders"))