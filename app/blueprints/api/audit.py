from flask import request, jsonify, g
from datetime import datetime

from . import api_bp
from decorators import token_required, api_role_required, api_subscription_required
from app.services import audit_service


@api_bp.route("/audit", methods=["GET"])
@token_required
@api_role_required("owner", "super_admin")
@api_subscription_required
def search_audit():
    action = request.args.get("action")
    actor_id = request.args.get("actor_id")
    branch_id = request.args.get("branch_id")
    q = request.args.get("q")
    date_from = request.args.get("from")
    date_to = request.args.get("to")
    limit = int(request.args.get("limit", 200))
    skip = int(request.args.get("skip", 0))

    def _parse(s):
        if not s:
            return None
        try:
            return datetime.fromisoformat(s.replace("Z", ""))
        except Exception:
            return None

    result = audit_service.query(
        g.api_user.tenant_id,
        action=action, actor_id=actor_id, branch_id=branch_id,
        date_from=_parse(date_from), date_to=_parse(date_to),
        q=q, limit=limit, skip=skip,
    )
    return jsonify(result)


@api_bp.route("/audit/actions", methods=["GET"])
@token_required
@api_role_required("owner", "super_admin")
@api_subscription_required
def list_actions():
    return jsonify({"actions": audit_service.distinct_actions(g.api_user.tenant_id)})