from datetime import datetime
from extensions import mongo
from utils import oid


def create(tenant_id, subject, description=None, tenant_code=None):
    tid = oid(tenant_id)
    doc = {
        "tenant_id": tid,
        "tenant_code": tenant_code,
        "subject": (subject or "Dispute").strip(),
        "description": (description or "").strip() or None,
        "status": "open",
        "created_at": datetime.utcnow(),
    }
    return mongo.db.disputes.insert_one(doc).inserted_id


def list_all(limit=200):
    cur = mongo.db.disputes.find({}).sort("created_at", -1).limit(limit)
    return list(cur)


def set_status(dispute_id, status):
    did = oid(dispute_id)
    if not did:
        return False
    if status not in ("open", "resolved", "rejected"):
        return False
    res = mongo.db.disputes.update_one(
        {"_id": did},
        {"$set": {"status": status, "updated_at": datetime.utcnow()}},
    )
    return res.modified_count == 1