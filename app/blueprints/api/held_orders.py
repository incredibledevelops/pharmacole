from flask import request, jsonify, g
from . import api_bp
from decorators import token_required, api_role_required, api_subscription_required
from app.services import held_order_service


@api_bp.route("/held-orders", methods=["GET"])
@token_required
@api_subscription_required
def list_held():
    rows = held_order_service.list_for_tenant(g.api_user.tenant_id, limit=200)
    return jsonify({"items": [{
        "id": str(h["_id"]),
        "label": h.get("label"),
        "items": [
            {"name": i["name"], "qty": i["qty"], "price": i["price"]}
            for i in h.get("items", [])
        ],
        "total_amount": h.get("total_amount"),
        "created_at": h["created_at"].isoformat() if h.get("created_at") else None,
    } for h in rows]})


@api_bp.route("/held-orders", methods=["POST"])
@token_required
@api_role_required("cashier", "owner")
@api_subscription_required
def hold():
    data = request.get_json(silent=True) or {}
    try:
        hid = held_order_service.hold(
            tenant_id=g.api_user.tenant_id,
            cashier=g.api_user,
            items=data.get("items") or [],
            label=data.get("label"),
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True, "id": str(hid)}), 201


@api_bp.route("/held-orders/<held_id>", methods=["DELETE"])
@token_required
@api_role_required("cashier", "owner")
@api_subscription_required
def delete_held(held_id):
    ok = held_order_service.delete(g.api_user.tenant_id, held_id)
    return jsonify({"ok": ok}), 200 if ok else 404


@api_bp.route("/held-orders/<held_id>/resume", methods=["POST"])
@token_required
@api_role_required("cashier", "owner")
@api_subscription_required
def resume(held_id):
    h = held_order_service.get(g.api_user.tenant_id, held_id)
    if not h:
        return jsonify({"error": "Not found"}), 404
    held_order_service.delete(g.api_user.tenant_id, held_id)
    return jsonify({
        "items": [{
            "id": str(i["inventory_id"]),
            "name": i["name"],
            "price": i["price"],
            "qty": i["qty"],
        } for i in h.get("items", [])]
    })