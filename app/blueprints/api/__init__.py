from flask import Blueprint, jsonify

api_bp = Blueprint("api", __name__, url_prefix="/api/v1")


@api_bp.route("/healthz", methods=["GET"])
def healthz():
    from datetime import datetime
    from extensions import mongo
    try:
        mongo.db.command("ping")
        return jsonify({"status": "ok", "time": datetime.utcnow().isoformat()}), 200
    except Exception as e:
        return jsonify({"status": "degraded", "error": str(e)}), 503


from flask import g as _g  # noqa: E402
from app.services.entitlement_service import tenant_has_feature  # noqa: E402

_API_OPEN_PREFIXES = (
    "/api/v1/auth/",
    "/api/v1/healthz",
    "/api/v1/receipts/",
)


@api_bp.before_request
def _gate_api():
    from flask import request as _req
    path = _req.path
    if any(path.startswith(p) for p in _API_OPEN_PREFIXES):
        return None
    user = getattr(_g, "api_user", None)
    tenant = getattr(_g, "api_tenant", None)
    if not user:
        return None
    if user.role == "super_admin":
        return None
    if not tenant:
        return jsonify({"error": "Tenant not found"}), 403
    if not tenant_has_feature(tenant._id, "api_access"):
        return jsonify({
            "error": "Your plan does not include API access",
            "code": "tier_upgrade_required",
            "feature": "api_access",
            "upgrade_url": "/owner/subscription",
        }), 402
    return None


import importlib
import logging

_log = logging.getLogger(__name__)

_SUBMODULES = [
    "auth",
    "branches",
    "inventory",
    "sales",
    "held_orders",
    "receipts",
    "audit",
    "branding",
]

for _name in _SUBMODULES:
    try:
        importlib.import_module(f"{__name__}.{_name}")
    except Exception as _e:
        _log.error("api submodule '%s' failed to import: %s", _name, _e)