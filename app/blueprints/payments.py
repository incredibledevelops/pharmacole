import uuid
from datetime import datetime
from flask import (
    Blueprint, request, jsonify, redirect, url_for, current_app, flash,
)
from flask_login import login_required, current_user

from models import find_tenant_by_id
from extensions import limiter
from app.services import payments_service, tenant_service
from utils import oid

payments_bp = Blueprint("payments", __name__, url_prefix="/payments")


# ---------------------------------------------------------------------------
# Initialize a Paystack transaction
# ---------------------------------------------------------------------------

@payments_bp.route("/initialize", methods=["POST"])
@login_required
@limiter.limit("20 per hour")
def initialize():
    if current_user.role != "owner":
        return jsonify({"error": "Only the owner can pay."}), 403

    tenant = find_tenant_by_id(current_user.tenant_id)
    if not tenant:
        return jsonify({"error": "Pharmacy record not found."}), 404

    amount = float(tenant.subscription_amount)
    reference = f"PHC-{tenant.tenant_code}-{uuid.uuid4().hex[:12].upper()}"

    try:
        data = payments_service.initialize_transaction(
            email=current_user.email,
            amount_ghs=amount,
            reference=reference,
            metadata={
                "tenant_code": tenant.tenant_code,
                "pharmacy_name": tenant.pharmacy_name,
                "custom_fields": [
                    {
                        "display_name": "Tenant",
                        "variable_name": "tenant_code",
                        "value": tenant.tenant_code,
                    }
                ],
            },
        )
    except payments_service.PaystackError as e:
        current_app.logger.warning("Paystack init failed: %s", e)
        return jsonify({"error": str(e)}), 502

    # Persist as pending
    payments_service.record_payment_intent(
        tenant_id=tenant._id,
        amount=amount,
        reference=reference,
        status="pending",
    )

    return jsonify({
        "reference": data.get("reference") or reference,
        "access_code": data.get("access_code"),
        "authorization_url": data.get("authorization_url"),
    })


# ---------------------------------------------------------------------------
# Verify after inline popup succeeds
# ---------------------------------------------------------------------------

@payments_bp.route("/verify", methods=["POST", "GET"])
@login_required
@limiter.limit("40 per hour")
def verify_ajax():
    reference = (request.args.get("reference") or "").strip()
    if not reference:
        return jsonify({"error": "Missing reference."}), 400

    record = payments_service.find_by_reference(reference)
    if not record:
        return jsonify({"error": "Unknown payment reference."}), 404

    if str(record.get("tenant_id")) != str(oid(current_user.tenant_id)):
        return jsonify({"error": "This payment does not belong to your account."}), 403

    if record.get("status") == "success":
        return jsonify({"ok": True, "message": "Already verified."})

    try:
        data = payments_service.verify_transaction(reference)
    except payments_service.PaystackError as e:
        return jsonify({"error": str(e)}), 502

    status = (data.get("status") or "").lower()
    if status != "success":
        payments_service.mark_failed(reference, reason=data.get("gateway_response"))
        return jsonify({"error": "Payment was not successful."}), 400

    expected_kobo = int(round(float(record.get("amount", 0)) * 100))
    if int(data.get("amount", 0)) < expected_kobo:
        payments_service.mark_failed(reference, reason="Amount mismatch")
        return jsonify({"error": "Payment amount did not match."}), 400

    # Mark paid + activate tenant
    payments_service.mark_paid(reference, data)
    customer_code = (data.get("customer") or {}).get("customer_code")
    tenant_service.activate(record["tenant_id"], paystack_customer_code=customer_code)

    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Synchronous redirect callback (if you configure Paystack callback_url)
# ---------------------------------------------------------------------------

@payments_bp.route("/callback", methods=["GET"])
@login_required
def callback():
    reference = (request.args.get("reference") or "").strip()
    if not reference:
        flash("Payment reference missing.", "danger")
        return redirect(url_for("auth.payment"))

    try:
        data = payments_service.verify_transaction(reference)
        if (data.get("status") or "").lower() == "success":
            payments_service.mark_paid(reference, data)
            record = payments_service.find_by_reference(reference)
            if record:
                customer_code = (data.get("customer") or {}).get("customer_code")
                tenant_service.activate(
                    record["tenant_id"], paystack_customer_code=customer_code
                )
            flash("Payment received. Your workspace is now active.", "success")
            return redirect(url_for("owner.dashboard"))
        else:
            payments_service.mark_failed(reference, reason=data.get("gateway_response"))
            flash("Payment was not successful.", "danger")
    except payments_service.PaystackError as e:
        flash(f"Verification error: {e}", "danger")

    return redirect(url_for("auth.payment"))