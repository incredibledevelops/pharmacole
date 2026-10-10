from datetime import datetime
from flask import request, has_request_context, g
from flask_login import current_user
from extensions import mongo
from utils import oid, client_ip, device_fingerprint


def log(action: str, tenant_id=None, target=None, meta=None,
        actor_id=None, actor_role=None, branch_id=None):
    """Write an audit log entry. Never raises."""
    try:
        if has_request_context():
            ip = client_ip(request)
            fp = device_fingerprint(request)
            ua = request.headers.get("User-Agent", "")[:300]
        else:
            ip = fp = ua = None

        if actor_id is None and current_user and getattr(current_user, "is_authenticated", False):
            actor_id = oid(current_user._id)
            actor_role = actor_role or current_user.role
            if tenant_id is None and current_user.tenant_id:
                tenant_id = oid(current_user.tenant_id)
            if branch_id is None and getattr(current_user, "branch_id", None):
                branch_id = oid(current_user.branch_id)

        mongo.db.audit_logs.insert_one({
            "actor_id": actor_id,
            "actor_role": actor_role,
            "tenant_id": tenant_id,
            "branch_id": branch_id,
            "target": target,
            "action": action,
            "meta": meta or {},
            "ip": ip,
            "device_fingerprint": fp,
            "user_agent": ua,
            "created_at": datetime.utcnow(),
        })
    except Exception:
        pass


def query(tenant_id, *, action=None, actor_id=None, branch_id=None,
          date_from=None, date_to=None, q=None, limit=200, skip=0):
    """Searchable audit log reader (used by owner dashboard + API)."""
    tid = oid(tenant_id)
    if not tid:
        return {"items": [], "total": 0}

    flt = {"tenant_id": tid}
    if action:
        flt["action"] = action
    if actor_id:
        aid = oid(actor_id)
        if aid:
            flt["actor_id"] = aid
    if branch_id:
        bid = oid(branch_id)
        if bid:
            flt["branch_id"] = bid
    if date_from or date_to:
        flt["created_at"] = {}
        if date_from:
            flt["created_at"]["$gte"] = date_from
        if date_to:
            flt["created_at"]["$lte"] = date_to
    if q:
        import re
        rx = re.compile(re.escape(q), re.IGNORECASE)
        flt["$or"] = [
            {"action": rx},
            {"target": rx},
            {"meta.note": rx},
        ]

    total = mongo.db.audit_logs.count_documents(flt)
    cur = (mongo.db.audit_logs.find(flt)
           .sort("created_at", -1)
           .skip(max(0, skip))
           .limit(min(limit, 500)))
    items = []
    for d in cur:
        d["_id"] = str(d["_id"])
        if d.get("actor_id"): d["actor_id"] = str(d["actor_id"])
        if d.get("tenant_id"): d["tenant_id"] = str(d["tenant_id"])
        if d.get("branch_id"): d["branch_id"] = str(d["branch_id"])
        d["created_at"] = d.get("created_at").isoformat() if d.get("created_at") else None
        items.append(d)
    return {"items": items, "total": total}


def distinct_actions(tenant_id):
    tid = oid(tenant_id)
    if not tid:
        return []
    return sorted(mongo.db.audit_logs.distinct("action", {"tenant_id": tid}))