from functools import wraps
from datetime import datetime
from flask import redirect, url_for, flash, abort
from flask_login import current_user

from extensions import mongo
from utils import oid


def role_required(*roles):
    """Allow only authenticated users with one of the given roles."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("auth.login"))
            if current_user.role not in roles:
                flash("You don't have access to that page.", "danger")
                return redirect(_dashboard_for(current_user.role))
            return f(*args, **kwargs)
        return wrapper
    return decorator


def _dashboard_for(role):
    mapping = {
        "owner": "owner.dashboard",
        "pharmacist": "pharmacist.dashboard",
        "cashier": "cashier.pos",
        "super_admin": "super_admin.dashboard",
    }
    endpoint = mapping.get(role, "auth.login")
    try:
        return url_for(endpoint)
    except Exception:
        return url_for("auth.login")


def subscription_required(f):
    """Ensure the current tenant has an active, unexpired subscription."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        if current_user.role == "super_admin":
            return f(*args, **kwargs)

        tenant_id = oid(current_user.tenant_id)
        if not tenant_id:
            flash("Your account is not linked to a pharmacy.", "danger")
            return redirect(url_for("auth.logout"))

        tenant = mongo.db.tenants.find_one({"_id": tenant_id})
        if not tenant:
            flash("Pharmacy record not found.", "danger")
            return redirect(url_for("auth.logout"))

        if tenant.get("subscription_status") != "active":
            return redirect(url_for("main.subscription_locked"))

        expires = tenant.get("subscription_expires_at")
        if expires is None:
            # No expiry set — treat as locked to be safe
            _mark_expired(tenant_id)
            return redirect(url_for("main.subscription_locked"))

        if isinstance(expires, str):
            try:
                expires = datetime.fromisoformat(expires.replace("Z", ""))
            except Exception:
                _mark_expired(tenant_id)
                return redirect(url_for("main.subscription_locked"))

        if expires < datetime.utcnow():
            _mark_expired(tenant_id)
            return redirect(url_for("main.subscription_locked"))

        return f(*args, **kwargs)
    return wrapper


def _mark_expired(tenant_id):
    try:
        mongo.db.tenants.update_one(
            {"_id": tenant_id},
            {"$set": {"subscription_status": "expired"}},
        )
        mongo.db.subscription_events.insert_one({
            "tenant_id": tenant_id,
            "event_type": "auto_expired",
            "created_at": datetime.utcnow(),
        })
    except Exception:
        pass