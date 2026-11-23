from flask import request, jsonify

from . import api_bp
from extensions import limiter
from models import find_user_by_id
from app.services import auth_service


@api_bp.route("/auth/refresh", methods=["POST"])
@limiter.limit("60 per hour")
def refresh():
    """
    Exchange a refresh token for a new access token.
    The refresh token's `sub` embeds the session_version, so password
    changes automatically invalidate outstanding refresh tokens.
    """
    data = request.get_json(silent=True) or {}
    token = (data.get("refresh") or "").strip()
    if not token:
        return jsonify({"error": "refresh token required"}), 400

    try:
        payload = auth_service.decode_token(token, expected_type="refresh")
    except auth_service.TokenError as e:
        return jsonify({"error": str(e)}), 401

    user = find_user_by_id(payload.get("sub"))
    if not user or not user.is_active:
        return jsonify({"error": "User not found or inactive"}), 401

    tokens = auth_service.issue_tokens(user)
    return jsonify(tokens), 200