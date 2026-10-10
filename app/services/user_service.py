from datetime import datetime
from pymongo.errors import DuplicateKeyError
from extensions import mongo
from models import User
from utils import oid
from app.services import entitlement_service


def create_user(email, password, full_name, role, tenant_id,
                phone=None, is_active=True, enforce_tier=True):
    email = (email or "").lower().strip()
    if not email:
        raise ValueError("Email is required")
    if role not in ("owner", "pharmacist", "cashier", "super_admin"):
        raise ValueError("Invalid role")

    if enforce_tier and role != "super_admin" and tenant_id:
        ok, msg = entitlement_service.can_add_user(tenant_id, role=role)
        if not ok:
            raise ValueError(msg)

    doc = {
        "email": email,
        "password_hash": User.hash_password(password),
        "full_name": (full_name or "").strip(),
        "role": role,
        "tenant_id": oid(tenant_id),
        "phone": (phone or "").strip() or None,
        "is_active": bool(is_active),
        "session_version": 1,
        "created_at": datetime.utcnow(),
    }
    try:
        res = mongo.db.users.insert_one(doc)
        return res.inserted_id
    except DuplicateKeyError:
        raise ValueError("Email is already registered")


def get_by_id(user_id):
    _id = oid(user_id)
    if not _id:
        return None
    data = mongo.db.users.find_one({"_id": _id})
    return User(data) if data else None


def get_by_email(email):
    if not email:
        return None
    data = mongo.db.users.find_one({"email": email.lower().strip()})
    return User(data) if data else None


def list_for_tenant(tenant_id):
    _id = oid(tenant_id)
    if not _id:
        return []
    cur = mongo.db.users.find({"tenant_id": _id}).sort("created_at", 1)
    return [User(d) for d in cur]


def list_by_role(tenant_id, role):
    _id = oid(tenant_id)
    if not _id:
        return []
    cur = mongo.db.users.find({"tenant_id": _id, "role": role}).sort("created_at", 1)
    return [User(d) for d in cur]


def toggle_active(user_id):
    _id = oid(user_id)
    if not _id:
        return False
    user = mongo.db.users.find_one({"_id": _id})
    if not user:
        return False
    new_state = not bool(user.get("is_active", True))

    if new_state and user.get("role") != "super_admin":
        tid = user.get("tenant_id")
        ok, msg = entitlement_service.can_add_user(tid, role=user.get("role"))
        if not ok:
            raise ValueError(msg)

    mongo.db.users.update_one({"_id": _id}, {"$set": {"is_active": new_state}})
    return new_state


def bump_session_version(user_id):
    _id = oid(user_id)
    if not _id:
        return
    mongo.db.users.update_one({"_id": _id}, {"$inc": {"session_version": 1}})


def change_password(user_id, new_password):
    _id = oid(user_id)
    if not _id:
        return False
    mongo.db.users.update_one(
        {"_id": _id},
        {
            "$set": {"password_hash": User.hash_password(new_password)},
            "$inc": {"session_version": 1},
        },
    )
    return True


def count_for_tenant(tenant_id):
    _id = oid(tenant_id)
    if not _id:
        return 0
    return mongo.db.users.count_documents({"tenant_id": _id})