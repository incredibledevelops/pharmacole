from datetime import datetime
from bson import ObjectId
from bson.errors import InvalidId
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from pymongo.errors import DuplicateKeyError

from extensions import mongo, login_manager
from utils import oid


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

class User(UserMixin):
    def __init__(self, data):
        self._id = str(data["_id"])
        self.email = (data.get("email") or "").lower().strip()
        self.full_name = data.get("full_name") or data.get("owner_name") or ""
        self.password_hash = data.get("password_hash") or ""
        self.role = data.get("role", "cashier")
        self.tenant_id = str(data["tenant_id"]) if data.get("tenant_id") else None
        self.is_active_user = bool(data.get("is_active", True))
        self.phone = data.get("phone")
        self.created_at = data.get("created_at") or datetime.utcnow()
        self.session_version = int(data.get("session_version", 1))
        self.data = data

    def get_id(self):
        return f"{self._id}:{self.session_version}"

    @property
    def is_active(self):
        return self.is_active_user

    @property
    def name(self):
        return self.full_name or self.email

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    @staticmethod
    def hash_password(password: str) -> str:
        return generate_password_hash(password)


# ---------------------------------------------------------------------------
# Tenant
# ---------------------------------------------------------------------------

class Tenant:
    def __init__(self, data):
        self._id = str(data["_id"])
        self.pharmacy_name = data.get("pharmacy_name", "Pharmacy")
        self.tenant_code = data.get("tenant_code", "—")
        self.owner_email = (data.get("owner_email") or "").lower().strip()
        self.owner_name = data.get("owner_name")
        self.owner_phone = data.get("owner_phone")
        self.address = data.get("address")
        self.subscription_status = data.get("subscription_status", "pending")
        self.subscription_amount = float(data.get("subscription_amount", 500.00))
        self.subscription_started_at = data.get("subscription_started_at")
        self.subscription_expires_at = data.get("subscription_expires_at")
        self.paystack_customer_code = data.get("paystack_customer_code")
        self.created_at = data.get("created_at") or datetime.utcnow()
        self.data = data

    @staticmethod
    def generate_code():
        import secrets
        import string
        chars = string.ascii_uppercase + string.digits
        for _ in range(10):
            code = "GH-" + "".join(secrets.choice(chars) for _ in range(6))
            if not mongo.db.tenants.find_one({"tenant_code": code}, {"_id": 1}):
                return code
        raise RuntimeError("Could not generate a unique tenant code")


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def find_user_by_id(user_id):
    """Accepts either 'hex' or 'hex:version'."""
    if not user_id:
        return None
    raw = str(user_id)
    version = None
    if ":" in raw:
        raw, _, v = raw.partition(":")
        try:
            version = int(v)
        except ValueError:
            version = None

    _id = oid(raw)
    if not _id:
        return None

    data = mongo.db.users.find_one({"_id": _id})
    if not data:
        return None

    if version is not None and int(data.get("session_version", 1)) != version:
        return None

    return User(data)


def find_user_by_email(email):
    if not email:
        return None
    data = mongo.db.users.find_one({"email": email.lower().strip()})
    return User(data) if data else None


def find_tenant_by_id(tenant_id):
    _id = oid(tenant_id)
    if not _id:
        return None
    data = mongo.db.tenants.find_one({"_id": _id})
    return Tenant(data) if data else None


def find_tenant_by_code(code):
    if not code:
        return None
    data = mongo.db.tenants.find_one({"tenant_code": code.upper().strip()})
    return Tenant(data) if data else None


# ---------------------------------------------------------------------------
# Flask-Login user loader
# ---------------------------------------------------------------------------

@login_manager.user_loader
def _load_user(user_id):
    return find_user_by_id(user_id)


# ---------------------------------------------------------------------------
# Index creation
# ---------------------------------------------------------------------------

def ensure_indexes():
    db = mongo.db

    # tenants
    db.tenants.create_index("tenant_code", unique=True)
    db.tenants.create_index("owner_email", unique=True)
    db.tenants.create_index("paystack_customer_code", sparse=True)

    # users
    db.users.create_index("email", unique=True)
    db.users.create_index("tenant_id")
    db.users.create_index([("tenant_id", 1), ("role", 1)])

    # inventory
    db.inventory.create_index(
        [("tenant_id", 1), ("sku", 1), ("batch_number", 1)],
        unique=True,
        partialFilterExpression={"batch_number": {"$exists": True, "$gt": ""}},
    )
    db.inventory.create_index([("tenant_id", 1), ("expiry_date", 1)])
    db.inventory.create_index([("tenant_id", 1), ("quantity", 1)])

    # sales
    db.sales.create_index("receipt_no", unique=True)
    db.sales.create_index([("tenant_id", 1), ("timestamp", -1)])
    db.sales.create_index([("tenant_id", 1), ("cashier_id", 1)])

    # payments
    db.payments.create_index("paystack_reference", unique=True, sparse=True)
    db.payments.create_index([("tenant_id", 1), ("paid_at", -1)])
    db.payments.create_index([("tenant_id", 1), ("status", 1)])

    # prescriptions
    db.prescriptions.create_index([("tenant_id", 1), ("status", 1)])
    db.prescriptions.create_index([("tenant_id", 1), ("created_at", -1)])

    # suppliers
    db.suppliers.create_index([("tenant_id", 1), ("name", 1)], unique=True)

    # stock_adjustments
    db.stock_adjustments.create_index([("tenant_id", 1), ("created_at", -1)])
    db.stock_adjustments.create_index("inventory_id")

    # held_orders
    db.held_orders.create_index([("tenant_id", 1), ("cashier_id", 1), ("created_at", -1)])

    # disputes
    db.disputes.create_index([("tenant_id", 1), ("created_at", -1)])
    db.disputes.create_index("status")

    # audit_logs
    db.audit_logs.create_index([("tenant_id", 1), ("created_at", -1)])
    db.audit_logs.create_index([("actor_id", 1), ("action", 1)])

    # subscription_events
    db.subscription_events.create_index([("tenant_id", 1), ("created_at", -1)])
    db.subscription_events.create_index("event_type")