from flask import request, jsonify, g
from . import api_bp
from decorators import token_required, api_role_required, api_subscription_required, api_feature_required
from app.services import supplier_service, audit_service

@api_bp.route("/suppliers", methods=["GET"])
@token_required
@api_subscription_required
@api_feature_required("suppliers")
def list_suppliers():
    items = supplier_service.list_for_tenant(g.api_user.tenant_id)
    return jsonify({"items": [{
        "id": str(s["_id"]),
        "name": s.get("name"),
        "phone": s.get("phone"),
        "email": s.get("email"),
        "address": s.get("address"),
        "created_at": s["created_at"].isoformat() if s.get("created_at") else None,
    } for s in items]})

@api_bp.route("/suppliers", methods=["POST"])
@token_required
@api_role_required("owner")
@api_subscription_required
@api_feature_required("suppliers")
def create_supplier():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Supplier name is required"}), 400

    try:
        sid = supplier_service.create_supplier(
            tenant_id=g.api_user.tenant_id,
            name=name,
            phone=data.get("phone"),
            email=data.get("email"),
            address=data.get("address"),
        )
        audit_service.log("supplier.add", meta={"name": name})
        return jsonify({"id": str(sid)}), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400