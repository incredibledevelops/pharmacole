from datetime import datetime
from pymongo.errors import DuplicateKeyError
from extensions import mongo
from models import User
from utils import oid


def create_user(email, password, full_name, role, tenant_id,
                phone=None, is_active=True):
    email = (email or "").lower().strip()
    if not email:
        raise ValueError("Email is required")
    if role not in ("owner", "pharmacist", "cashier", "super_admin"):
        raise ValueError("Invalid role")

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
    cur = mongo.db.users.find(
        {"tenant_id": _id}
    ).sort("created_at", 1)
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
    mongo.db.users.update_one({"_id": _id}, {"$set": {"is_active": new_state}})
    return new_state


def bump_session_version(user_id):
    """Invalidate all existing sessions for the user."""
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