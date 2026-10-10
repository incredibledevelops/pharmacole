from datetime import datetime
from extensions import mongo
from utils import oid
from models import Branch, Tenant
from app.services import entitlement_service


def create_branch(tenant_id, name, address=None, phone=None, is_default=False):
    tid = oid(tenant_id)
    if not tid:
        raise ValueError("Invalid tenant")

    name = (name or "").strip()
    if not name:
        raise ValueError("Branch name is required")

    tenant = mongo.db.tenants.find_one({"_id": tid})
    if not tenant:
        raise ValueError("Tenant not found")

    ok, msg = entitlement_service.can_add_branch(tid)
    if not ok:
        raise ValueError(msg)

    current = mongo.db.branches.count_documents({"tenant_id": tid, "is_active": True})

    doc = {
        "tenant_id": tid,
        "name": name,
        "branch_code": Branch.generate_code(tid, name),
        "address": (address or "").strip() or None,
        "phone": (phone or "").strip() or None,
        "is_default": bool(is_default and current == 0),
        "is_active": True,
        "created_at": datetime.utcnow(),
    }
    return mongo.db.branches.insert_one(doc).inserted_id


def list_for_tenant(tenant_id, active_only=True):
    tid = oid(tenant_id)
    if not tid:
        return []
    q = {"tenant_id": tid}
    if active_only:
        q["is_active"] = True
    cur = mongo.db.branches.find(q).sort("created_at", 1)
    return [Branch(d) for d in cur]


def get(tenant_id, branch_id):
    tid = oid(tenant_id)
    bid = oid(branch_id)
    if not tid or not bid:
        return None
    data = mongo.db.branches.find_one({"_id": bid, "tenant_id": tid})
    return Branch(data) if data else None


def get_default(tenant_id):
    tid = oid(tenant_id)
    if not tid:
        return None
    data = mongo.db.branches.find_one({"tenant_id": tid, "is_default": True})
    if not data:
        data = mongo.db.branches.find_one({"tenant_id": tid})
    return Branch(data) if data else None


def update(tenant_id, branch_id, **fields):
    tid = oid(tenant_id)
    bid = oid(branch_id)
    if not tid or not bid:
        return False
    allowed = {"name", "address", "phone", "is_active"}
    clean = {k: v for k, v in fields.items() if k in allowed}
    if not clean:
        return False
    clean["updated_at"] = datetime.utcnow()
    res = mongo.db.branches.update_one({"_id": bid, "tenant_id": tid}, {"$set": clean})
    return res.modified_count == 1


def set_default(tenant_id, branch_id):
    tid = oid(tenant_id)
    bid = oid(branch_id)
    if not tid or not bid:
        return False
    mongo.db.branches.update_many({"tenant_id": tid}, {"$set": {"is_default": False}})
    mongo.db.branches.update_one(
        {"_id": bid, "tenant_id": tid}, {"$set": {"is_default": True}}
    )
    return True


def ensure_default(tenant_id):
    tid = oid(tenant_id)
    if not tid:
        return None
    existing = mongo.db.branches.find_one({"tenant_id": tid})
    if existing:
        return Branch(existing)
    tenant = mongo.db.tenants.find_one({"_id": tid})
    if not tenant:
        return None
    doc = {
        "tenant_id": tid,
        "name": f"{tenant.get('pharmacy_name', 'Pharmacy')} (Main)",
        "branch_code": Branch.generate_code(tid, "MAIN"),
        "address": tenant.get("address"),
        "phone": tenant.get("owner_phone"),
        "is_default": True,
        "is_active": True,
        "created_at": datetime.utcnow(),
    }
    bid = mongo.db.branches.insert_one(doc).inserted_id
    return get(tid, bid)