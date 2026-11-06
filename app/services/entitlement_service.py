"""
Tier entitlement engine.

Single source of truth for "can this tenant do X?"
"""
from datetime import datetime

from flask import current_app, flash, redirect, url_for, jsonify, g
from flask_login import current_user

from extensions import mongo
from utils import oid


def tier_config(tier: str) -> dict:
    tiers = current_app.config["PRICING_TIERS"]
    return tiers.get(tier, tiers.get("pro", {}))


def get_tenant_tier(tenant_id) -> str:
    tid = oid(tenant_id)
    if not tid:
        return "pro"
    t = mongo.db.tenants.find_one({"_id": tid}, {"tier": 1})
    return (t or {}).get("tier", "pro")


def limits_for(tenant_id) -> dict:
    return tier_config(get_tenant_tier(tenant_id))


def tenant_has_feature(tenant_id, feature: str) -> bool:
    return feature in limits_for(tenant_id).get("features", [])


def current_user_has_feature(feature: str) -> bool:
    if not current_user or not current_user.is_authenticated:
        return False
    if current_user.role == "super_admin":
        return True
    if not current_user.tenant_id:
        return False
    return tenant_has_feature(current_user.tenant_id, feature)


def count_active_branches(tenant_id) -> int:
    tid = oid(tenant_id)
    if not tid:
        return 0
    return mongo.db.branches.count_documents({"tenant_id": tid, "is_active": True})


def count_active_users(tenant_id) -> int:
    tid = oid(tenant_id)
    if not tid:
        return 0
    return mongo.db.users.count_documents({
        "tenant_id": tid,
        "is_active": True,
        "role": {"$ne": "super_admin"},
    })


def can_add_branch(tenant_id):
    lim = limits_for(tenant_id).get("branches", 1)
    if lim == -1:
        return True, None
    current = count_active_branches(tenant_id)
    if current >= lim:
        tier_label = limits_for(tenant_id).get("label", "current")
        return False, (
            f"Your {tier_label} plan allows {lim} branch"
            f"{'es' if lim != 1 else ''}. Upgrade to add more."
        )
    return True, None


def can_add_user(tenant_id, role="cashier"):
    if role == "super_admin":
        return True, None
    lim = limits_for(tenant_id).get("users", -1)
    if lim == -1:
        return True, None
    current = count_active_users(tenant_id)
    if current >= lim:
        tier_label = limits_for(tenant_id).get("label", "current")
        return False, (
            f"Your {tier_label} plan allows {lim} user"
            f"{'s' if lim != 1 else ''}. Upgrade to add more."
        )
    return True, None


def downgrade_blocker(tenant_id, target_tier: str):
    """
    Return None if the tenant can downgrade to `target_tier`, or a human
    readable reason string if they can't.

    Rationale: blocking only *new* resources on a downgrade lets a tenant
    keep 5 branches on a 1-branch plan. We refuse the downgrade until the
    tenant reduces their resource usage to fit the target plan.
    """
    tiers = current_app.config["PRICING_TIERS"]
    if target_tier not in tiers:
        return "Unknown plan"

    target = tiers[target_tier]
    branch_limit = target.get("branches", 1)
    user_limit = target.get("users", -1)

    if branch_limit != -1:
        branches = count_active_branches(tenant_id)
        if branches > branch_limit:
            return (
                f"You have {branches} active branches but the "
                f"{target.get('label', target_tier)} plan allows {branch_limit}. "
                f"Deactivate branches before switching."
            )

    if user_limit != -1:
        users = count_active_users(tenant_id)
        if users > user_limit:
            return (
                f"You have {users} active users but the "
                f"{target.get('label', target_tier)} plan allows {user_limit}. "
                f"Deactivate users before switching."
            )

    return None


def can_downgrade_to(tenant_id, target_tier: str):
    blocker = downgrade_blocker(tenant_id, target_tier)
    return (blocker is None), blocker


def can_use_feature(tenant_id, feature):
    if tenant_has_feature(tenant_id, feature):
        return True, None
    lim = limits_for(tenant_id)
    return False, (
        f"The '{feature.replace('_', ' ')}' feature is not included in your "
        f"{lim.get('label', 'current')} plan. Upgrade to unlock it."
    )


def feature_required(feature: str):
    from functools import wraps

    def deco(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("auth.login"))
            if current_user.role == "super_admin":
                return f(*args, **kwargs)
            if not current_user.tenant_id:
                flash("Your account is not linked to a pharmacy.", "danger")
                return redirect(url_for("auth.logout"))
            if not tenant_has_feature(current_user.tenant_id, feature):
                lim = limits_for(current_user.tenant_id)
                flash(
                    f"Your {lim.get('label', 'current')} plan does not include "
                    f"'{feature.replace('_', ' ')}'. Upgrade to unlock it.",
                    "warning",
                )
                return redirect(url_for("owner.subscription"))
            return f(*args, **kwargs)
        return wrapper
    return deco


def api_feature_required(feature: str):
    from functools import wraps

    def deco(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            user = getattr(g, "api_user", None)
            if not user:
                return jsonify({"error": "Unauthenticated"}), 401
            if user.role == "super_admin":
                return f(*args, **kwargs)
            if not user.tenant_id:
                return jsonify({"error": "No tenant"}), 403
            if not tenant_has_feature(user.tenant_id, feature):
                return jsonify({
                    "error": "Tier does not include this feature",
                    "feature": feature,
                    "code": "tier_upgrade_required",
                    "upgrade_url": "/owner/subscription",
                }), 402
            return f(*args, **kwargs)
        return wrapper
    return deco


def register_jinja(app):
    app.jinja_env.globals.update(
        tenant_has_feature=tenant_has_feature,
        tenant_tier=lambda tid: get_tenant_tier(tid),
        tenant_limits=lambda tid: limits_for(tid),
        current_user_has_feature=current_user_has_feature,
    )