from flask import jsonify, g

from . import api_bp
from decorators import token_required


@api_bp.route("/me", methods=["GET"])
@token_required
def me():
    """
    Return the authenticated API user + tenant summary + API base URL.
    Used by the owner audit page and other browser views that mint a
    short-lived JWT from `/api/session-token`.
    """
    user = g.api_user
    tenant = g.api_tenant

    return jsonify({
        "api_base": "/api/v1",
        "user": {
            "id": user._id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "tenant_id": user.tenant_id,
            "branch_id": user.branch_id,
        },
        "tenant": {
            "id": tenant._id if tenant else None,
            "code": tenant.tenant_code if tenant else None,
            "name": tenant.pharmacy_name if tenant else None,
            "tier": tenant.tier if tenant else None,
            "subscription_status": tenant.subscription_status if tenant else None,
        } if tenant else None,
    })