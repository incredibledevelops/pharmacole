from datetime import datetime
import requests
from flask import current_app
from extensions import mongo
from utils import oid


class PaystackError(Exception):
    pass


def _headers():
    key = current_app.config["PAYSTACK_SECRET_KEY"]
    if not key:
        raise PaystackError("Paystack secret key is not configured")
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def initialize_transaction(email, amount_ghs, reference, metadata=None):
    """Create a Paystack transaction. Returns the Paystack response data."""
    url = f"{current_app.config['PAYSTACK_BASE_URL']}/transaction/initialize"
    payload = {
        "email": email,
        "amount": int(round(float(amount_ghs) * 100)),  # pesewas
        "currency": current_app.config["SUBSCRIPTION_CURRENCY"],
        "reference": reference,
        "metadata": metadata or {},
        "callback_url": f"{current_app.config['BASE_URL']}/payments/verify",
    }
    try:
        r = requests.post(url, json=payload, headers=_headers(), timeout=15)
    except requests.RequestException as e:
        raise PaystackError(f"Network error contacting Paystack: {e}")

    try:
        data = r.json()
    except ValueError:
        raise PaystackError("Invalid response from Paystack")

    if not data.get("status"):
        raise PaystackError(data.get("message") or "Paystack initialization failed")

    return data.get("data") or {}


def verify_transaction(reference):
    """Verify a transaction by reference. Returns Paystack data dict."""
    url = f"{current_app.config['PAYSTACK_BASE_URL']}/transaction/verify/{reference}"
    try:
        r = requests.get(url, headers=_headers(), timeout=15)
    except requests.RequestException as e:
        raise PaystackError(f"Network error contacting Paystack: {e}")

    try:
        data = r.json()
    except ValueError:
        raise PaystackError("Invalid response from Paystack")

    if not data.get("status"):
        raise PaystackError(data.get("message") or "Paystack verification failed")

    return data.get("data") or {}


def record_payment_intent(tenant_id, amount, reference, status="pending"):
    tid = oid(tenant_id)
    if not tid:
        raise ValueError("Invalid tenant")

    doc = {
        "tenant_id": tid,
        "amount": float(amount),
        "currency": current_app.config["SUBSCRIPTION_CURRENCY"],
        "paystack_reference": reference,
        "status": status,
        "created_at": datetime.utcnow(),
        "paid_at": None,
        "paystack_data": None,
    }
    mongo.db.payments.insert_one(doc)
    return reference


def find_by_reference(reference):
    if not reference:
        return None
    return mongo.db.payments.find_one({"paystack_reference": reference})


def mark_paid(reference, paystack_data):
    mongo.db.payments.update_one(
        {"paystack_reference": reference},
        {
            "$set": {
                "status": "success",
                "paid_at": datetime.utcnow(),
                "paystack_data": _sanitize(paystack_data),
            }
        },
    )


def mark_failed(reference, reason=None):
    mongo.db.payments.update_one(
        {"paystack_reference": reference},
        {
            "$set": {
                "status": "failed",
                "failure_reason": reason,
                "updated_at": datetime.utcnow(),
            }
        },
    )


def list_for_tenant(tenant_id, limit=100):
    tid = oid(tenant_id)
    if not tid:
        return []
    cur = mongo.db.payments.find({"tenant_id": tid}).sort("created_at", -1).limit(limit)
    return list(cur)


def list_all(skip=0, limit=100):
    cur = (
        mongo.db.payments
        .find({})
        .sort("created_at", -1)
        .skip(max(0, skip))
        .limit(max(1, min(limit, 500)))
    )
    return list(cur)


def recent(limit=10):
    return list(mongo.db.payments.find({}).sort("created_at", -1).limit(limit))


def _sanitize(data):
    """Strip anything that isn't JSON-serializable or is sensitive."""
    if not isinstance(data, dict):
        return None
    allowed_keys = {
        "reference", "status", "amount", "currency", "channel",
        "paid_at", "created_at", "gateway_response", "message",
        "fees", "customer", "authorization",
    }
    out = {}
    for k in allowed_keys:
        if k in data:
            out[k] = data[k]
    return out