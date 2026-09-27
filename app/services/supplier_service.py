from datetime import datetime
from pymongo.errors import DuplicateKeyError
from extensions import mongo
from utils import oid


def create_supplier(tenant_id, name, phone=None, email=None, address=None):
    tid = oid(tenant_id)
    if not tid:
        raise ValueError("Invalid tenant")

    name = (name or "").strip()
    if not name:
        raise ValueError("Supplier name is required")

    doc = {
        "tenant_id": tid,
        "name": name,
        "phone": (phone or "").strip() or None,
        "email": (email or "").strip() or None,
        "address": (address or "").strip() or None,
        "created_at": datetime.utcnow(),
    }
    try:
        res = mongo.db.suppliers.insert_one(doc)
        return res.inserted_id
    except DuplicateKeyError:
        raise ValueError("A supplier with that name already exists")


def list_for_tenant(tenant_id):
    tid = oid(tenant_id)
    if not tid:
        return []
    cur = mongo.db.suppliers.find({"tenant_id": tid}).sort("name", 1)
    return list(cur)


def names_for_tenant(tenant_id):
    return [s["name"] for s in list_for_tenant(tenant_id) if s.get("name")]