from flask import request, jsonify, g
from . import api_bp
from decorators import (
    token_required, api_role_required, api_subscription_required,
    api_feature_required,
)
from app.services import branch_service, audit_service


@api_bp.route("/branches", methods=["GET"])
@token_required
@api_subscription_required
@api_feature_required("multi_branch")
def list_branches():
    user = g.api_user
    if user.role in ("owner", "pharmacist"):
        rows = branch_service.list_for_tenant(user.tenant_id, active_only=False)
    else:
        b = branch_service.get(user.tenant_id, user.branch_id) if user.branch_id else None
        rows = [b] if b else []
    return jsonify({
        "items": [{
            "id": b._id, "name": b.name, "code": b.code,
            "address": b.address, "phone": b.phone,
            "is_default": b.is_default, "is_active": b.is_active,
        } for b in rows]
    })


@api_bp.route("/branches", methods=["POST"])
@token_required
@api_role_required("owner")
@api_subscription_required
@api_feature_required("multi_branch")
def create_branch():
    data = request.get_json(silent=True) or {}
    try:
        bid = branch_service.create_branch(
            g.api_user.tenant_id,
            name=data.get("name"),
            address=data.get("address"),
            phone=data.get("phone"),
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    audit_service.log("branch.create", target=str(bid),
                      meta={"name": data.get("name")})
    b = branch_service.get(g.api_user.tenant_id, bid)
    return jsonify({"id": b._id, "name": b.name, "code": b.code}), 201


@api_bp.route("/branches/<branch_id>", methods=["PATCH"])
@token_required
@api_role_required("owner")
@api_subscription_required
@api_feature_required("multi_branch")
def update_branch(branch_id):
    data = request.get_json(silent=True) or {}
    ok = branch_service.update(g.api_user.tenant_id, branch_id, **data)
    if not ok:
        return jsonify({"error": "Could not update branch"}), 400
    audit_service.log("branch.update", target=branch_id,
                      meta={"fields": list(data.keys())})
    return jsonify({"ok": True})


@api_bp.route("/branches/<branch_id>/default", methods=["POST"])
@token_required
@api_role_required("owner")
@api_subscription_required
@api_feature_required("multi_branch")
def set_default(branch_id):
    ok = branch_service.set_default(g.api_user.tenant_id, branch_id)
    if not ok:
        return jsonify({"error": "Could not set default"}), 400
    audit_service.log("branch.set_default", target=branch_id)
    return jsonify({"ok": True})