from datetime import datetime, timedelta
from pymongo.errors import DuplicateKeyError
from extensions import mongo
from models import Tenant
from utils import oid, _coerce_dt


def create_tenant(pharmacy_name, owner_name, owner_email, owner_phone=None,
                  address=None, subscription_amount=None, tier="pro"):
    from flask import current_app
    tiers = current_app.config["PRICING_TIERS"]
    if tier not in tiers:
        tier = "pro"
    amount = subscription_amount if subscription_amount is not None else tiers[tier]["amount"]

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
        "tier": tier,
        "pending_tier": None,
        "logo_url": None,
        "receipt_header": None,
        "receipt_footer": None,
        "tin": None,
        "business_reg_no": None,
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
    cur = (mongo.db.tenants.find({})
           .sort("created_at", -1)
           .skip(max(0, skip))
           .limit(max(1, min(limit, 500))))
    return [Tenant(d) for d in cur]


def count_all():
    return mongo.db.tenants.count_documents({})


def stats():
    total = mongo.db.tenants.count_documents({})
    active = mongo.db.tenants.count_documents({"subscription_status": "active"})
    pending = mongo.db.tenants.count_documents({"subscription_status": "pending"})
    expired = mongo.db.tenants.count_documents({"subscription_status": "expired"})
    return {"total": total, "active": active, "pending": pending, "expired": expired}


def activate(tenant_id, days=None, paystack_customer_code=None):
    """
    Activate or renew. Also applies any pending tier change.

    Extends from the current expiry when the tenant is still active, so
    early renewals stack days. Handles both datetime and ISO-string
    expiries via _coerce_dt.
    """
    from flask import current_app
    days = days or current_app.config["SUBSCRIPTION_DURATION_DAYS"]
    _id = oid(tenant_id)
    if not _id:
        return False

    now = datetime.utcnow()
    tenant = mongo.db.tenants.find_one({"_id": _id})
    if not tenant:
        return False

    pending_tier = tenant.get("pending_tier")
    tiers = current_app.config["PRICING_TIERS"]
    applied_tier = None
    if pending_tier and pending_tier in tiers and pending_tier != tenant.get("tier"):
        applied_tier = pending_tier

    current_expiry = _coerce_dt(tenant.get("subscription_expires_at"))
    base = now
    if current_expiry and current_expiry > now:
        base = current_expiry
    new_expiry = base + timedelta(days=days)

    update = {
        "subscription_status": "active",
        "subscription_started_at": _coerce_dt(tenant.get("subscription_started_at")) or now,
        "subscription_expires_at": new_expiry,
    }
    if paystack_customer_code:
        update["paystack_customer_code"] = paystack_customer_code

    if applied_tier:
        update["tier"] = applied_tier
        update["subscription_amount"] = float(tiers[applied_tier]["amount"])
        update["pending_tier"] = None

    mongo.db.tenants.update_one({"_id": _id}, {"$set": update})

    mongo.db.subscription_events.insert_one({
        "tenant_id": _id,
        "event_type": "activated",
        "days": days,
        "new_expiry": new_expiry,
        "tier": applied_tier or tenant.get("tier"),
        "created_at": now,
    })
    return True


def mark_expired(tenant_id):
    _id = oid(tenant_id)
    if not _id:
        return
    mongo.db.tenants.update_one({"_id": _id}, {"$set": {"subscription_status": "expired"}})
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


def update_branding(tenant_id, logo_url=None, receipt_header=None,
                    receipt_footer=None, tin=None, business_reg_no=None):
    _id = oid(tenant_id)
    if not _id:
        return False
    patch = {}
    if logo_url is not None:
        patch["logo_url"] = logo_url
    if receipt_header is not None:
        patch["receipt_header"] = receipt_header
    if receipt_footer is not None:
        patch["receipt_footer"] = receipt_footer
    if tin is not None:
        patch["tin"] = tin
    if business_reg_no is not None:
        patch["business_reg_no"] = business_reg_no
    if not patch:
        return False
    patch["updated_at"] = datetime.utcnow()
    mongo.db.tenants.update_one({"_id": _id}, {"$set": patch})
    return True


def set_pending_tier(tenant_id, tier):
    from flask import current_app
    from app.services import entitlement_service

    if tier not in current_app.config["PRICING_TIERS"]:
        return False
    _id = oid(tenant_id)
    if not _id:
        return False
    tenant = mongo.db.tenants.find_one({"_id": _id})
    if not tenant:
        return False

    current_tier = tenant.get("tier")
    if tier == current_tier:
        mongo.db.tenants.update_one({"_id": _id}, {"$set": {"pending_tier": None}})
        return True

    if _tier_rank(tier) < _tier_rank(current_tier):
        ok, msg = entitlement_service.can_downgrade_to(_id, tier)
        if not ok:
            return False

    mongo.db.tenants.update_one({"_id": _id}, {"$set": {"pending_tier": tier}})
    return True


def clear_pending_tier(tenant_id):
    _id = oid(tenant_id)
    if not _id:
        return False
    mongo.db.tenants.update_one({"_id": _id}, {"$set": {"pending_tier": None}})
    return True


def apply_pending_tier(tenant_id):
    from flask import current_app
    from app.services import entitlement_service

    _id = oid(tenant_id)
    if not _id:
        return False
    tenant = mongo.db.tenants.find_one({"_id": _id})
    if not tenant:
        return False
    pending = tenant.get("pending_tier")
    tiers = current_app.config["PRICING_TIERS"]
    if not pending or pending not in tiers:
        return False

    current_tier = tenant.get("tier", "pro")
    if _tier_rank(pending) < _tier_rank(current_tier):
        ok, msg = entitlement_service.can_downgrade_to(_id, pending)
        if not ok:
            mongo.db.tenants.update_one(
                {"_id": _id},
                {"$set": {"pending_tier": None}},
            )
            mongo.db.subscription_events.insert_one({
                "tenant_id": _id,
                "event_type": "downgrade_blocked",
                "from_tier": current_tier,
                "to_tier": pending,
                "reason": msg,
                "created_at": datetime.utcnow(),
            })
            return False

    amount = float(tiers[pending]["amount"])
    mongo.db.tenants.update_one(
        {"_id": _id},
        {"$set": {
            "tier": pending,
            "subscription_amount": amount,
            "pending_tier": None,
        }},
    )
    mongo.db.subscription_events.insert_one({
        "tenant_id": _id,
        "event_type": "tier_change",
        "tier": pending,
        "amount": amount,
        "created_at": datetime.utcnow(),
    })
    return True


def _tier_rank(tier):
    from flask import current_app
    order = current_app.config.get("TIER_ORDER", [])
    try:
        return order.index(tier)
    except ValueError:
        return 0


def change_tier(tenant_id, tier):
    """Deprecated: use set_pending_tier + apply_pending_tier instead."""
    return set_pending_tier(tenant_id, tier)