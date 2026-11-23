from flask import request, jsonify, g
from . import api_bp
from decorators import token_required, api_role_required, api_subscription_required
from app.services import user_service, audit_service
from models import find_user_by_id

@api_bp.route("/employees", methods=["GET"])
@token_required
@api_role_required("owner")
@api_subscription_required
def list_employees():
    users = user_service.list_for_tenant(g.api_user.tenant_id)
    return jsonify({"items": [{
        "id": u._id,
        "name": u.name,
        "email": u.email,
        "role": u.role,
        "is_active": u.is_active,
        "phone": u.phone,
        "created_at": u.created_at.isoformat() if u.created_at else None,
    } for u in users]})

@api_bp.route("/employees", methods=["POST"])
@token_required
@api_role_required("owner")
@api_subscription_required
def create_employee():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").lower().strip()
    password = data.get("password") or ""
    full_name = (data.get("full_name") or "").strip()
    role = data.get("role")
    phone = data.get("phone")

    if role not in ("pharmacist", "cashier"):
        return jsonify({"error": "Invalid role"}), 400
    if not full_name or not email or len(password) < 6:
        return jsonify({"error": "Name, email and password (min 6 chars) are required"}), 400

    try:
        uid = user_service.create_user(
            email=email,
            password=password,
            full_name=full_name,
            role=role,
            tenant_id=g.api_user.tenant_id,
            phone=phone,
        )
        audit_service.log("employee.add", meta={"email": email, "role": role})
        return jsonify({"id": str(uid)}), 201
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

@api_bp.route("/employees/<user_id>/toggle", methods=["POST"])
@token_required
@api_role_required("owner")
@api_subscription_required
def toggle_employee(user_id):
    target = user_service.get_by_id(user_id)
    if not target or str(target.tenant_id) != str(g.api_user.tenant_id):
        return jsonify({"error": "Not found"}), 404

    if target.role == "pharmacist" and target.is_active:
        active_pharmacists = [
            u for u in user_service.list_by_role(g.api_user.tenant_id, "pharmacist")
            if u.is_active and u._id != target._id
        ]
        if not active_pharmacists:
            return jsonify({"error": "Cannot deactivate the last active pharmacist"}), 400

    try:
        new_state = user_service.toggle_active(user_id)
        audit_service.log("employee.toggle", target=user_id, meta={"active": new_state})
        return jsonify({"ok": True, "is_active": new_state})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400