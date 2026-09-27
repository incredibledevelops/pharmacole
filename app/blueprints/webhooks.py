import hmac
import hashlib
from flask import Blueprint, request, jsonify, current_app

from extensions import mongo
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
        if reference:
            record = payments_service.find_by_reference(reference)
            if record and record.get("status") != "success":
                payments_service.mark_paid(reference, data)
                customer_code = (data.get("customer") or {}).get("customer_code")
                tenant_service.activate(
                    record["tenant_id"], paystack_customer_code=customer_code
                )

    elif event in ("charge.failed", "transfer.failed"):
        reference = data.get("reference")
        if reference:
            payments_service.mark_failed(reference, reason=data.get("gateway_response"))

    # Always return 200 so Paystack stops retrying
    return jsonify({"status": "ok"}), 200