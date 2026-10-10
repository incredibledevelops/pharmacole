from flask import request, jsonify, g, Response, current_app, url_for
from . import api_bp
from decorators import token_required, api_role_required, api_subscription_required
from extensions import mongo
from utils import oid
from app.services import receipt_service, notification_service
from models import find_tenant_by_id


def _find_sale(tenant_id, receipt_no):
    tid = oid(tenant_id)
    return mongo.db.sales.find_one({"tenant_id": tid, "receipt_no": receipt_no})


def _sale_dict(s, tenant=None):
    return {
        "receipt_no": s["receipt_no"],
        "timestamp": s["timestamp"].strftime("%Y-%m-%d %H:%M"),
        "cashier_name": s.get("cashier_name"),
        "customer_name": s.get("customer_name"),
        "items": s.get("items", []),
        "subtotal": s.get("subtotal", 0.0),
        "vat": s.get("vat", 0.0),
        "discount": s.get("discount", 0.0),
        "total_amount": s.get("total_amount", 0.0),
        "payment_method": s.get("payment_method"),
        "branch_name": None,
    }


@api_bp.route("/receipts/<receipt_no>.pdf", methods=["GET"])
@token_required
@api_subscription_required
def receipt_pdf(receipt_no):
    s = _find_sale(g.api_user.tenant_id, receipt_no)
    if not s:
        return jsonify({"error": "Receipt not found"}), 404
    tenant = find_tenant_by_id(g.api_user.tenant_id)
    pdf = receipt_service.receipt_pdf(tenant, _sale_dict(s))
    return Response(
        pdf, mimetype="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{receipt_no}.pdf"'},
    )


@api_bp.route("/receipts/<receipt_no>/email", methods=["POST"])
@token_required
@api_role_required("cashier", "owner", "pharmacist")
@api_subscription_required
def email_receipt(receipt_no):
    data = request.get_json(silent=True) or {}
    to_email = (data.get("email") or "").strip()
    if not to_email:
        return jsonify({"error": "email required"}), 400

    s = _find_sale(g.api_user.tenant_id, receipt_no)
    if not s:
        return jsonify({"error": "Receipt not found"}), 404
    tenant = find_tenant_by_id(g.api_user.tenant_id)
    sale = _sale_dict(s)

    pdf = None
    try:
        pdf = receipt_service.receipt_pdf(tenant, sale)
    except Exception:
        pdf = None

    try:
        notification_service.email_receipt(to_email, tenant, sale, pdf_bytes=pdf)
    except Exception as e:
        return jsonify({"error": str(e)}), 502

    return jsonify({"ok": True})


@api_bp.route("/receipts/<receipt_no>/whatsapp", methods=["POST"])
@token_required
@api_role_required("cashier", "owner", "pharmacist")
@api_subscription_required
def whatsapp_receipt(receipt_no):
    data = request.get_json(silent=True) or {}
    phone = (data.get("phone") or "").strip()
    if not phone:
        return jsonify({"error": "phone required"}), 400

    s = _find_sale(g.api_user.tenant_id, receipt_no)
    if not s:
        return jsonify({"error": "Receipt not found"}), 404
    tenant = find_tenant_by_id(g.api_user.tenant_id)
    sale = _sale_dict(s)

    try:
        notification_service.whatsapp_receipt(phone, tenant, sale)
    except Exception as e:
        return jsonify({"error": str(e)}), 502

    return jsonify({"ok": True})


# NEW — public verification page (used by QR)
@api_bp.route("/receipts/<receipt_no>/verify", methods=["GET"])
def verify_receipt(receipt_no):
    s = mongo.db.sales.find_one({"receipt_no": receipt_no})
    if not s:
        return jsonify({"valid": False}), 404
    return jsonify({
        "valid": True,
        "receipt_no": s["receipt_no"],
        "total_amount": s.get("total_amount"),
        "timestamp": s["timestamp"].isoformat(),
        "payment_method": s.get("payment_method"),
        "items_count": len(s.get("items", [])),
    })