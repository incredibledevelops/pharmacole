from datetime import datetime, timedelta
from pymongo.errors import DuplicateKeyError
from extensions import mongo
from models import Tenant
from utils import oid


def create_tenant(pharmacy_name, owner_name, owner_email, owner_phone=None,
                  address=None, subscription_amount=None):
    """Create a tenant with status='pending'. Returns the inserted _id."""
    from flask import current_app
    amount = subscription_amount
    if amount is None:
        amount = current_app.config["SUBSCRIPTION_AMOUNT"]

    doc = {
        "pharmacy_name": (pharmacy_name or "").strip(),
        "tenant_code": Tenant.generate_code(),
        "owner_name": (owner_name or "").strip(),
        "owner_email": (owner_email or "").lower().strip(),
        "owner_phone": (owner_phone or "").strip() or None,
        "address": (address or "").strip() or None,
        "subscription_status": "pending",
        "subscription_amount": float(amount),
        "subscription_started_at": None,
        "subscription_expires_at": None,
        "paystack_customer_code": None,
        "created_at": datetime.utcnow(),
    }
    res = mongo.db.tenants.insert_one(doc)
    return res.inserted_id


def get_by_id(tenant_id):
    _id = oid(tenant_id)
    if not _id:
        return None
    data = mongo.db.tenants.find_one({"_id": _id})
    return Tenant(data) if data else None


def get_by_code(code):
    if not code:
        return None
    data = mongo.db.tenants.find_one({"tenant_code": code.upper().strip()})
    return Tenant(data) if data else None


def get_by_owner_email(email):
    if not email:
        return None
    data = mongo.db.tenants.find_one({"owner_email": email.lower().strip()})
    return Tenant(data) if data else None


def list_all(skip=0, limit=100):
    cur = (
        mongo.db.tenants
        .find({})
        .sort("created_at", -1)
        .skip(max(0, skip))
        .limit(max(1, min(limit, 500)))
    )
    return [Tenant(d) for d in cur]


def count_all():
    return mongo.db.tenants.count_documents({})


def stats():
    total = mongo.db.tenants.count_documents({})
    active = mongo.db.tenants.count_documents({"subscription_status": "active"})
    pending = mongo.db.tenants.count_documents({"subscription_status": "pending"})
    expired = mongo.db.tenants.count_documents({"subscription_status": "expired"})
    return {
        "total": total,
        "active": active,
        "pending": pending,
        "expired": expired,
    }


def activate(tenant_id, days=None, paystack_customer_code=None):
    """Activate or renew a tenant's subscription."""
    from flask import current_app
    days = days or current_app.config["SUBSCRIPTION_DURATION_DAYS"]
    _id = oid(tenant_id)
    if not _id:
        return False

    now = datetime.utcnow()
    tenant = mongo.db.tenants.find_one({"_id": _id})
    if not tenant:
        return False

    current_expiry = tenant.get("subscription_expires_at")
    base = now
    if current_expiry and isinstance(current_expiry, datetime) and current_expiry > now:
        base = current_expiry  # stack renewal on top of remaining days

    new_expiry = base + timedelta(days=days)

    update = {
        "subscription_status": "active",
        "subscription_started_at": tenant.get("subscription_started_at") or now,
        "subscription_expires_at": new_expiry,
    }
    if paystack_customer_code:
        update["paystack_customer_code"] = paystack_customer_code

    mongo.db.tenants.update_one({"_id": _id}, {"$set": update})

    mongo.db.subscription_events.insert_one({
        "tenant_id": _id,
        "event_type": "activated",
        "days": days,
        "new_expiry": new_expiry,
        "created_at": now,
    })
    return True


def mark_expired(tenant_id):
    _id = oid(tenant_id)
    if not _id:
        return
    mongo.db.tenants.update_one(
        {"_id": _id}, {"$set": {"subscription_status": "expired"}}
    )
    mongo.db.subscription_events.insert_one({
        "tenant_id": _id,
        "event_type": "expired",
        "created_at": datetime.utcnow(),
    })


def monthly_recurring_revenue():
    pipeline = [
        {"$match": {"subscription_status": "active"}},
        {"$group": {"_id": None, "total": {"$sum": "$subscription_amount"}}},
    ]
    res = list(mongo.db.tenants.aggregate(pipeline))
    return float(res[0]["total"]) if res else 0.0