from flask import request, jsonify, g
from datetime import datetime

from . import api_bp
from extensions import limiter
from models import find_user_by_email, find_tenant_by_code, find_tenant_by_id
from app.services import auth_service, branch_service
from decorators import token_required


@api_bp.route("/auth/login", methods=["POST"])
@limiter.limit("20 per minute")
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").lower().strip()
    password = data.get("password") or ""
    tenant_code = (data.get("tenant_code") or "").strip()
    login_type = (data.get("login_type") or "tenant").strip()

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    user = auth_service.authenticate(email, password)
    if not user:
        return jsonify({"error": "Invalid credentials"}), 401

    if login_type == "tenant":
        if user.role == "super_admin":
            return jsonify({"error": "Use super admin login"}), 403
        tenant = None
        if tenant_code:
            tenant = find_tenant_by_code(tenant_code)
            if not tenant:
                return jsonify({"error": "Tenant not found"}), 404
            if str(user.tenant_id) != str(tenant._id):
                return jsonify({"error": "Account not in that tenant"}), 403
        else:
            tenant = find_tenant_by_id(user.tenant_id)

    elif login_type == "super":
        if user.role != "super_admin":
            return jsonify({"error": "Not a super admin"}), 403
        tenant = None
    else:
        return jsonify({"error": "Invalid login_type"}), 400

    tokens = auth_service.issue_tokens(user)

    branch = None
    if tenant:
        branch = branch_service.ensure_default(tenant._id)

    response = {
        **tokens,
        "tenant": {
            "id": tenant._id if tenant else None,
            "code": tenant.tenant_code if tenant else None,
            "name": tenant.pharmacy_name if tenant else None,
            "tier": tenant.tier if tenant else None,
            "subscription_status": tenant.subscription_status if tenant else None,
        } if tenant else None,
        "branch": {
            "id": branch._id, "name": branch.name, "code": branch.code
        } if branch else None,
    }
    return jsonify(response), 200


@api_bp.route("/auth/refresh", methods=["POST"])
@limiter.limit("60 per hour")
def refresh():
    data = request.get_json(silent=True) or {}
    token = data.get("refresh") or ""
    if not token:
        return jsonify({"error": "Missing refresh token"}), 400
    try:
        payload = auth_service.decode_token(token, expected_type="refresh")
    except auth_service.TokenError as e:
        return jsonify({"error": str(e)}), 401

    from models import find_user_by_id
    user = find_user_by_id(payload["sub"])
    if not user or not user.is_active:
        return jsonify({"error": "User not found"}), 401
    return jsonify(auth_service.issue_tokens(user)), 200


@api_bp.route("/auth/me", methods=["GET"])
@token_required
def me():
    u = g.api_user
    t = g.api_tenant
    return jsonify({
        "user": {
            "id": u._id,
            "email": u.email,
            "name": u.name,
            "role": u.role,
            "tenant_id": u.tenant_id,
            "branch_id": u.branch_id,
        },
        "tenant": {
            "id": t._id,
            "code": t.tenant_code,
            "name": t.pharmacy_name,
            "tier": t.tier,
            "pending_tier": t.pending_tier,
            "subscription_status": t.subscription_status,
            "subscription_expires_at": t.subscription_expires_at.isoformat() if t.subscription_expires_at else None,
            "logo_url": t.logo_url,
        } if t else None,
    }), 200


@api_bp.route("/auth/logout", methods=["POST"])
@token_required
def logout():
    from extensions import mongo
    from utils import oid
    mongo.db.users.update_one(
        {"_id": oid(g.api_user._id)}, {"$inc": {"session_version": 1}}
    )
    return jsonify({"ok": True}), 200