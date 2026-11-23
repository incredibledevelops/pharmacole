import uuid
from flask import request, jsonify, g, current_app

from . import api_bp
from decorators import token_required, api_role_required, api_subscription_required
from extensions import limiter
from models import find_tenant_by_id
from app.services import payments_service, tenant_service
from utils import oid


def _tier_to_charge(tenant, requested):
    tiers = current_app.config["PRICING_TIERS"]
    if requested and requested in tiers:
        return requested
    if tenant.pending_tier and tenant.pending_tier in tiers:
        return tenant.pending_tier
    return tenant.tier if tenant.tier in tiers else "pro"


@api_bp.route("/payments/initialize", methods=["POST"])
@token_required
@api_role_required("owner")
@limiter.limit("20 per hour")
def api_initialize():
    tenant = find_tenant_by_id(g.api_user.tenant_id)
    if not tenant:
        return jsonify({"error": "Pharmacy record not found"}), 404

    body = request.get_json(silent=True) or {}
    requested_tier = (body.get("tier") or "").strip().lower()
    tiers = current_app.config["PRICING_TIERS"]

    if requested_tier and requested_tier not in tiers:
        return jsonify({"error": "Unknown tier"}), 400

    charge_tier = _tier_to_charge(tenant, requested_tier)

    if charge_tier != tenant.tier:
        tenant_service.set_pending_tier(tenant._id, charge_tier)

    amount = float(tiers[charge_tier]["amount"])
    reference = f"PHC-{tenant.tenant_code}-{uuid.uuid4().hex[:12].upper()}"

    try:
        data = payments_service.initialize_transaction(
            email=g.api_user.email,
            amount_ghs=amount,
            reference=reference,
            metadata={
                "tenant_code": tenant.tenant_code,
                "pharmacy_name": tenant.pharmacy_name,
                "tier": charge_tier,
                "channel": "mobile_app",
                "custom_fields": [
                    {"display_name": "Tenant", "variable_name": "tenant_code",
                     "value": tenant.tenant_code},
                    {"display_name": "Tier", "variable_name": "tier",
                     "value": charge_tier},
                ],
            },
        )
    except payments_service.PaystackError as e:
        current_app.logger.warning("Paystack init failed: %s", e)
        return jsonify({"error": str(e)}), 502

    payments_service.record_payment_intent(
        tenant_id=tenant._id,
        amount=amount,
        reference=reference,
        status="pending",
        tier=charge_tier,
    )

    return jsonify({
        "reference": data.get("reference") or reference,
        "access_code": data.get("access_code"),
        "authorization_url": data.get("authorization_url"),
        "amount": amount,
        "tier": charge_tier,
        "public_key": current_app.config["PAYSTACK_PUBLIC_KEY"],
    })


@api_bp.route("/payments/verify", methods=["POST"])
@token_required
@api_role_required("owner")
@limiter.limit("40 per hour")
def api_verify():
    body = request.get_json(silent=True) or {}
    reference = (body.get("reference") or request.args.get("reference") or "").strip()
    if not reference:
        return jsonify({"error": "Missing reference"}), 400

    record = payments_service.find_by_reference(reference)
    if not record:
        return jsonify({"error": "Unknown payment reference"}), 404

    if str(record.get("tenant_id")) != str(oid(g.api_user.tenant_id)):
        return jsonify({"error": "This payment does not belong to your account"}), 403

    if record.get("status") == "success":
        return jsonify({"ok": True, "message": "Already verified"})

    try:
        data = payments_service.verify_transaction(reference)
    except payments_service.PaystackError as e:
        return jsonify({"error": str(e)}), 502

    status = (data.get("status") or "").lower()
    if status != "success":
        payments_service.mark_failed(reference, reason=data.get("gateway_response"))
        return jsonify({"error": "Payment was not successful"}), 400

    expected_kobo = int(round(float(record.get("amount", 0)) * 100))
    if int(data.get("amount", 0)) < expected_kobo:
        payments_service.mark_failed(reference, reason="Amount mismatch")
        return jsonify({"error": "Payment amount did not match"}), 400

    tenant_id = record["tenant_id"]
    payments_service.mark_paid(reference, data)
    tenant_service.apply_pending_tier(tenant_id)
    customer_code = (data.get("customer") or {}).get("customer_code")
    tenant_service.activate(tenant_id, paystack_customer_code=customer_code)

    return jsonify({"ok": True})


@api_bp.route("/payments/history", methods=["GET"])
@token_required
@api_role_required("owner")
@api_subscription_required
def api_history():
    rows = payments_service.list_for_tenant(g.api_user.tenant_id, limit=50)
    return jsonify({"items": [{
        "reference": p.get("paystack_reference"),
        "amount": p.get("amount"),
        "status": p.get("status"),
        "tier": p.get("tier"),
        "created_at": p["created_at"].isoformat() if p.get("created_at") else None,
        "paid_at": p["paid_at"].isoformat() if p.get("paid_at") else None,
    } for p in rows]})


@api_bp.route("/subscription/status", methods=["GET"])
@token_required
@api_subscription_required
def subscription_status():
    from app.services import entitlement_service
    tenant = g.api_tenant
    limits = entitlement_service.limits_for(tenant._id)
    return jsonify({
        "tier": tenant.tier,
        "pending_tier": tenant.pending_tier,
        "subscription_status": tenant.subscription_status,
        "expires_at": tenant.subscription_expires_at.isoformat()
            if tenant.subscription_expires_at else None,
        "amount": tenant.subscription_amount,
        "label": limits.get("label"),
        "features": limits.get("features", []),
        "limits": {
            "branches": limits.get("branches"),
            "users": limits.get("users"),
        },
        "usage": {
            "branches": entitlement_service.count_active_branches(tenant._id),
            "users": entitlement_service.count_active_users(tenant._id),
        },
    })