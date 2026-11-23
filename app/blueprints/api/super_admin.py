from flask import request, jsonify, g

from . import api_bp
from decorators import token_required, api_role_required
from models import find_tenant_by_id
from app.services import (
    tenant_service, user_service, payments_service,
    dispute_service,
)


@api_bp.route("/super/dashboard", methods=["GET"])
@token_required
@api_role_required("super_admin")
def sa_dashboard():
    stats = tenant_service.stats()
    mrr = tenant_service.monthly_recurring_revenue()
    recent_tenants = tenant_service.list_all(skip=0, limit=5)
    recent_payments = payments_service.recent(limit=5)

    return jsonify({
        "total_tenants": stats["total"],
        "active": stats["active"],
        "expired": stats["expired"] + stats["pending"],
        "mrr": mrr,
        "recent_tenants": [{
            "id": t._id,
            "name": t.pharmacy_name,
            "code": t.tenant_code,
            "owner_email": t.owner_email,
            "status": t.subscription_status,
            "tier": t.tier,
        } for t in recent_tenants],
        "recent_payments": [{
            "reference": p.get("paystack_reference"),
            "amount": p.get("amount"),
            "status": p.get("status"),
            "created_at": p["created_at"].isoformat() if p.get("created_at") else None,
            "paid_at": p["paid_at"].isoformat() if p.get("paid_at") else None,
        } for p in recent_payments],
    })


@api_bp.route("/super/tenants", methods=["GET"])
@token_required
@api_role_required("super_admin")
def sa_tenants():
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    per_page = 50
    skip = (page - 1) * per_page

    items = tenant_service.list_all(skip=skip, limit=per_page)
    total = tenant_service.count_all()

    return jsonify({
        "items": [{
            "id": t._id,
            "name": t.pharmacy_name,
            "code": t.tenant_code,
            "owner_name": t.owner_name,
            "owner_email": t.owner_email,
            "owner_phone": t.owner_phone,
            "address": t.address,
            "tier": t.tier,
            "status": t.subscription_status,
            "expires_at": t.subscription_expires_at.isoformat()
                if t.subscription_expires_at else None,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        } for t in items],
        "page": page,
        "per_page": per_page,
        "total": total,
        "has_next": (skip + per_page) < total,
    })


@api_bp.route("/super/tenants/<tenant_id>", methods=["GET"])
@token_required
@api_role_required("super_admin")
def sa_tenant_detail(tenant_id):
    tenant = find_tenant_by_id(tenant_id)
    if not tenant:
        return jsonify({"error": "Not found"}), 404
    users = user_service.list_for_tenant(tenant._id)
    payments = payments_service.list_for_tenant(tenant._id, limit=50)

    return jsonify({
        "tenant": {
            "id": tenant._id,
            "name": tenant.pharmacy_name,
            "code": tenant.tenant_code,
            "owner_name": tenant.owner_name,
            "owner_email": tenant.owner_email,
            "owner_phone": tenant.owner_phone,
            "address": tenant.address,
            "tier": tenant.tier,
            "status": tenant.subscription_status,
            "amount": tenant.subscription_amount,
            "started_at": tenant.subscription_started_at.isoformat()
                if tenant.subscription_started_at else None,
            "expires_at": tenant.subscription_expires_at.isoformat()
                if tenant.subscription_expires_at else None,
        },
        "users": [{
            "id": u._id,
            "email": u.email,
            "name": u.name,
            "role": u.role,
            "is_active": u.is_active,
        } for u in users],
        "payments": [{
            "reference": p.get("paystack_reference"),
            "amount": p.get("amount"),
            "status": p.get("status"),
            "paid_at": p["paid_at"].isoformat() if p.get("paid_at") else None,
            "created_at": p["created_at"].isoformat() if p.get("created_at") else None,
        } for p in payments],
    })


@api_bp.route("/super/tenants/<tenant_id>/activate", methods=["POST"])
@token_required
@api_role_required("super_admin")
def sa_activate(tenant_id):
    data = request.get_json(silent=True) or {}
    try:
        days = int(data.get("days", 30))
    except (TypeError, ValueError):
        days = 30
    ok = tenant_service.activate(tenant_id, days=days)
    if not ok:
        return jsonify({"error": "Could not activate"}), 400
    return jsonify({"ok": True, "days": days})


@api_bp.route("/super/tenants/<tenant_id>/expire", methods=["POST"])
@token_required
@api_role_required("super_admin")
def sa_expire(tenant_id):
    tenant_service.mark_expired(tenant_id)
    return jsonify({"ok": True})


@api_bp.route("/super/billing", methods=["GET"])
@token_required
@api_role_required("super_admin")
def sa_billing():
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    per_page = 50
    skip = (page - 1) * per_page
    items = payments_service.list_all(skip=skip, limit=per_page)

    out = []
    for p in items:
        tenant = find_tenant_by_id(p.get("tenant_id"))
        out.append({
            "reference": p.get("paystack_reference"),
            "tenant_code": tenant.tenant_code if tenant else "—",
            "tenant_id": str(p.get("tenant_id")) if p.get("tenant_id") else None,
            "amount": p.get("amount"),
            "status": p.get("status"),
            "tier": p.get("tier"),
            "created_at": p["created_at"].isoformat() if p.get("created_at") else None,
            "paid_at": p["paid_at"].isoformat() if p.get("paid_at") else None,
        })
    return jsonify({"items": out, "page": page, "per_page": per_page})


@api_bp.route("/super/disputes", methods=["GET"])
@token_required
@api_role_required("super_admin")
def sa_disputes():
    items = dispute_service.list_all(limit=200)
    out = []
    for d in items:
        tc = d.get("tenant_code")
        if not tc and d.get("tenant_id"):
            t = find_tenant_by_id(d["tenant_id"])
            tc = t.tenant_code if t else "—"
        out.append({
            "id": str(d["_id"]),
            "tenant_code": tc,
            "subject": d.get("subject"),
            "description": d.get("description"),
            "status": d.get("status"),
            "created_at": d["created_at"].isoformat() if d.get("created_at") else None,
        })
    return jsonify({"items": out})


@api_bp.route("/super/disputes/<dispute_id>/status", methods=["POST"])
@token_required
@api_role_required("super_admin")
def sa_set_dispute(dispute_id):
    data = request.get_json(silent=True) or {}
    status = (data.get("status") or "").strip()
    ok = dispute_service.set_status(dispute_id, status)
    if not ok:
        return jsonify({"error": "Could not update"}), 400
    return jsonify({"ok": True})