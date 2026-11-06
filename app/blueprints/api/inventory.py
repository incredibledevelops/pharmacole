from flask import request, jsonify, g
from . import api_bp
from decorators import token_required, api_role_required, api_subscription_required
from app.services import inventory_service, audit_service
from app.services.inventory_service import _BRANCH_ANY
from utils import oid


def _serialize(item):
    if not item:
        return None
    return {
        "id": str(item["_id"]),
        "name": item.get("name"),
        "sku": item.get("sku"),
        "category": item.get("category"),
        "dosage_form": item.get("dosage_form"),
        "pack_size": item.get("pack_size"),
        "description": item.get("description"),
        "cost_price": item.get("cost_price"),
        "selling_price": item.get("selling_price"),
        "tax_rate": item.get("tax_rate"),
        "quantity": item.get("quantity"),
        "min_threshold": item.get("min_threshold"),
        "batch_number": item.get("batch_number"),
        "expiry_date": item["expiry_date"].isoformat() if item.get("expiry_date") else None,
        "supplier": item.get("supplier"),
        "branch_id": str(item["branch_id"]) if item.get("branch_id") else None,
        "updated_at": item["updated_at"].isoformat() if item.get("updated_at") else None,
    }


@api_bp.route("/inventory", methods=["GET"])
@token_required
@api_subscription_required
def list_inventory():
    q = request.args.get("q")
    try:
        limit = int(request.args.get("limit", 1000))
    except (TypeError, ValueError):
        limit = 1000

    # Branch scoping: if the JWT user has a branch, force it. Otherwise allow
    # an explicit ?branch_id= or fall back to "any branch".
    user_branch = oid(g.api_user.branch_id) if getattr(g.api_user, "branch_id", None) else None
    if user_branch is not None:
        branch = user_branch
    else:
        raw = request.args.get("branch_id")
        branch = oid(raw) if raw else _BRANCH_ANY

    rows = inventory_service.list_for_tenant(
        g.api_user.tenant_id, search=q, limit=min(limit, 5000), branch_id=branch,
    )
    return jsonify({"items": [_serialize(i) for i in rows]})


@api_bp.route("/inventory/<item_id>", methods=["GET"])
@token_required
@api_subscription_required
def get_item(item_id):
    item = inventory_service.get_item(g.api_user.tenant_id, item_id)
    if not item:
        return jsonify({"error": "Not found"}), 404
    # Branch guard for scoped users
    user_branch = oid(g.api_user.branch_id) if getattr(g.api_user, "branch_id", None) else None
    if user_branch is not None and item.get("branch_id") != user_branch:
        return jsonify({"error": "Not found"}), 404
    return jsonify(_serialize(item))


@api_bp.route("/inventory", methods=["POST"])
@token_required
@api_role_required("owner", "pharmacist")
@api_subscription_required
def create_item():
    data = request.get_json(silent=True) or {}
    user_branch = oid(g.api_user.branch_id) if getattr(g.api_user, "branch_id", None) else None
    branch_id = user_branch or data.get("branch_id") or g.api_user.branch_id
    try:
        iid = inventory_service.create_item(
            g.api_user.tenant_id, data, branch_id=branch_id,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"id": str(iid)}), 201


@api_bp.route("/inventory/<item_id>", methods=["PATCH"])
@token_required
@api_role_required("owner", "pharmacist")
@api_subscription_required
def update_item(item_id):
    data = request.get_json(silent=True) or {}
    # Branch guard for scoped users
    user_branch = oid(g.api_user.branch_id) if getattr(g.api_user, "branch_id", None) else None
    if user_branch is not None:
        item = inventory_service.get_item(g.api_user.tenant_id, item_id)
        if not item or item.get("branch_id") != user_branch:
            return jsonify({"error": "Not found"}), 404
    try:
        ok = inventory_service.update_item(g.api_user.tenant_id, item_id, data)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": ok})


@api_bp.route("/inventory/<item_id>", methods=["DELETE"])
@token_required
@api_role_required("owner", "pharmacist")
@api_subscription_required
def delete_item(item_id):
    user_branch = oid(g.api_user.branch_id) if getattr(g.api_user, "branch_id", None) else None
    if user_branch is not None:
        item = inventory_service.get_item(g.api_user.tenant_id, item_id)
        if not item or item.get("branch_id") != user_branch:
            return jsonify({"error": "Not found"}), 404
    try:
        inventory_service.delete_item(g.api_user.tenant_id, item_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True})


@api_bp.route("/inventory/<item_id>/adjust", methods=["POST"])
@token_required
@api_role_required("owner", "pharmacist")
@api_subscription_required
def adjust(item_id):
    data = request.get_json(silent=True) or {}
    user_branch = oid(g.api_user.branch_id) if getattr(g.api_user, "branch_id", None) else None
    if user_branch is not None:
        item = inventory_service.get_item(g.api_user.tenant_id, item_id)
        if not item or item.get("branch_id") != user_branch:
            return jsonify({"error": "Not found"}), 404
    try:
        new_qty = inventory_service.adjust_stock(
            g.api_user.tenant_id, item_id,
            delta=data.get("delta"),
            reason=data.get("reason"),
            actor_id=g.api_user._id,
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True, "quantity": new_qty})


@api_bp.route("/inventory/alerts/low-stock", methods=["GET"])
@token_required
@api_subscription_required
def low_stock():
    user_branch = oid(g.api_user.branch_id) if getattr(g.api_user, "branch_id", None) else None
    rows = inventory_service.low_stock(
        g.api_user.tenant_id, limit=100, branch_id=user_branch if user_branch else _BRANCH_ANY,
    )
    return jsonify({"items": [_serialize(i) for i in rows]})


@api_bp.route("/inventory/alerts/expiring", methods=["GET"])
@token_required
@api_subscription_required
def expiring():
    try:
        days = int(request.args.get("days", 30))
    except (TypeError, ValueError):
        days = 30
    user_branch = oid(g.api_user.branch_id) if getattr(g.api_user, "branch_id", None) else None
    rows = inventory_service.expiring_within(
        g.api_user.tenant_id, days=days,
        branch_id=user_branch if user_branch else _BRANCH_ANY,
    )
    return jsonify({"items": [_serialize(i) for i in rows]})