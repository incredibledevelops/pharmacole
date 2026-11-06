import hmac
import hashlib
from datetime import datetime

from flask import Blueprint, request, jsonify, current_app

from app.services import payments_service, tenant_service

webhooks_bp = Blueprint("webhooks", __name__, url_prefix="/webhooks")


@webhooks_bp.route("/paystack", methods=["POST"])
def paystack():
    secret = current_app.config["PAYSTACK_SECRET_KEY"]
    if not secret:
        return jsonify({"error": "Webhook not configured"}), 500

    signature = request.headers.get("x-paystack-signature", "")
    body = request.get_data() or b""

    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha512).hexdigest()
    if not hmac.compare_digest(expected, signature):
        current_app.logger.warning("Invalid Paystack webhook signature")
        return jsonify({"error": "Invalid signature"}), 401

    try:
        payload = request.get_json(force=True, silent=True) or {}
    except Exception:
        return jsonify({"error": "Invalid payload"}), 400

    event = payload.get("event")
    data = payload.get("data") or {}

    if event == "charge.success":
        reference = data.get("reference")
        if not reference:
            return jsonify({"status": "ignored"}), 200

        record = payments_service.find_by_reference(reference)
        if not record:
            current_app.logger.warning("Webhook for unknown reference %s", reference)
            return jsonify({"status": "ignored"}), 200

        # --- Idempotency: if we've already processed this payment, do NOT
        # extend the subscription again. Paystack can retry webhooks.
        if record.get("status") == "success":
            current_app.logger.info("Webhook replay for %s — already processed", reference)
            return jsonify({"status": "already_processed"}), 200

        try:
            payments_service.mark_paid(reference, data)
            tenant_service.apply_pending_tier(record["tenant_id"])
            customer_code = (data.get("customer") or {}).get("customer_code")
            tenant_service.activate(
                record["tenant_id"],
                paystack_customer_code=customer_code,
            )
        except Exception as e:
            current_app.logger.exception("Webhook processing failed for %s", reference)
            # Return 500 so Paystack retries. mark_paid is idempotent and
            # `activate` is guarded by the status check above.
            return jsonify({"error": "processing_failed"}), 500

    elif event in ("charge.failed", "transfer.failed"):
        reference = data.get("reference")
        if reference:
            payments_service.mark_failed(
                reference,
                reason=data.get("gateway_response"),
            )

    return jsonify({"status": "ok"}), 200