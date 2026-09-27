from datetime import datetime
from extensions import mongo
from utils import oid


def list_for_tenant(tenant_id, limit=200):
    tid = oid(tenant_id)
    if not tid:
        return []
    cur = mongo.db.prescriptions.find({"tenant_id": tid}).sort("created_at", -1).limit(limit)
    return list(cur)


def count_pending(tenant_id):
    tid = oid(tenant_id)
    if not tid:
        return 0
    return mongo.db.prescriptions.count_documents({"tenant_id": tid, "status": "pending"})


def create(tenant_id, patient_name, doctor_name=None, notes=None):
    tid = oid(tenant_id)
    if not tid:
        raise ValueError("Invalid tenant")
    doc = {
        "tenant_id": tid,
        "patient_name": (patient_name or "").strip(),
        "doctor_name": (doctor_name or "").strip() or None,
        "notes": (notes or "").strip() or None,
        "status": "pending",
        "created_at": datetime.utcnow(),
    }
    return mongo.db.prescriptions.insert_one(doc).inserted_id


def set_status(tenant_id, prescription_id, status):
    tid = oid(tenant_id)
    pid = oid(prescription_id)
    if not tid or not pid:
        return False
    if status not in ("pending", "dispensed", "cancelled"):
        return False
    res = mongo.db.prescriptions.update_one(
        {"_id": pid, "tenant_id": tid},
        {"$set": {"status": status, "updated_at": datetime.utcnow()}},
    )
    return res.modified_count == 1