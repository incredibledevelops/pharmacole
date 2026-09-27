from datetime import datetime
from flask_login import current_user
from extensions import mongo
from utils import oid


def log(action: str, tenant_id=None, target=None, meta=None):
    """Write an audit log entry. Never raises."""
    try:
        actor_id = None
        actor_role = None
        if current_user and getattr(current_user, "is_authenticated", False):
            actor_id = oid(current_user._id)
            actor_role = current_user.role
            if tenant_id is None and current_user.tenant_id:
                tenant_id = oid(current_user.tenant_id)

        mongo.db.audit_logs.insert_one({
            "actor_id": actor_id,
            "actor_role": actor_role,
            "tenant_id": tenant_id,
            "target": target,
            "action": action,
            "meta": meta or {},
            "created_at": datetime.utcnow(),
        })
    except Exception:
        pass