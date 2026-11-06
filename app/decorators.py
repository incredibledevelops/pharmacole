from functools import wraps
from datetime import datetime
from flask import redirect, url_for, flash, request, g, jsonify
from flask_login import current_user

from extensions import mongo
from utils import oid, _coerce_dt
from app.services.entitlement_service import (
    feature_required,
    api_feature_required,
    tenant_has_feature,
)


def role_required(*roles):
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

        expires = _coerce_dt(tenant.get("subscription_expires_at"))
        if expires is None:
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


def token_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        from app.services import auth_service
        from models import find_user_by_id, find_tenant_by_id

        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({"error": "Missing bearer token"}), 401

        token = auth.split(" ", 1)[1].strip()
        try:
            payload = auth_service.decode_token(token, expected_type="access")
        except auth_service.TokenError as e:
            return jsonify({"error": str(e)}), 401

        user = find_user_by_id(payload["sub"])
        if not user or not user.is_active:
            return jsonify({"error": "User not found or inactive"}), 401

        g.api_user = user
        g.api_tenant = find_tenant_by_id(user.tenant_id) if user.tenant_id else None
        g.api_payload = payload

        return f(*args, **kwargs)
    return wrapper


def api_role_required(*roles):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            user = getattr(g, "api_user", None)
            if not user:
                return jsonify({"error": "Unauthenticated"}), 401
            if user.role not in roles:
                return jsonify({"error": "Forbidden"}), 403
            return f(*args, **kwargs)
        return wrapper
    return decorator


def api_subscription_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        tenant = getattr(g, "api_tenant", None)
        user = getattr(g, "api_user", None)
        if not user:
            return jsonify({"error": "Unauthenticated"}), 401
        if user.role == "super_admin":
            return f(*args, **kwargs)
        if not tenant:
            return jsonify({"error": "Tenant not found"}), 403

        if tenant.subscription_status != "active":
            return jsonify({
                "error": "Subscription inactive",
                "code": "subscription_locked",
            }), 402

        exp = _coerce_dt(tenant.subscription_expires_at)
        if exp is not None and exp < datetime.utcnow():
            # Mark expired in background (best-effort, same as browser path).
            try:
                from utils import oid as _oid
                _mark_expired(_oid(tenant._id))
            except Exception:
                pass
            return jsonify({
                "error": "Subscription expired",
                "code": "subscription_locked",
            }), 402

        return f(*args, **kwargs)
    return wrapper


__all__ = [
    "role_required",
    "subscription_required",
    "token_required",
    "api_role_required",
    "api_subscription_required",
    "feature_required",
    "api_feature_required",
    "tenant_has_feature",
]