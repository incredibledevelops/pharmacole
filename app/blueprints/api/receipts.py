from flask import request, jsonify, g, Response
from . import api_bp
from decorators import token_required, api_role_required, api_subscription_required
from extensions import mongo
from utils import oid
from app.services import receipt_service, notification_service
from models import find_tenant_by_id, find_tenant_by_code


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


@api_bp.route("/receipts/<receipt_no>/sms", methods=["POST"])
@token_required
@api_role_required("cashier", "owner", "pharmacist")
@api_subscription_required
def sms_receipt(receipt_no):
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
        notification_service.sms_receipt(phone, tenant, sale)
    except Exception as e:
        return jsonify({"error": str(e)}), 502

    return jsonify({"ok": True})


@api_bp.route("/receipts/<receipt_no>/verify", methods=["GET"])
def verify_receipt(receipt_no):
    """Public verification endpoint used by the QR code on printed receipts."""
    tenant_code = (request.args.get("tenant") or "").strip().upper()
    receipt = (receipt_no or "").strip().upper()

    if not receipt:
        return jsonify({"valid": False}), 404

    sale = None
    if tenant_code:
        tenant = find_tenant_by_code(tenant_code)
        if not tenant:
            return jsonify({"valid": False}), 404
        sale = mongo.db.sales.find_one({
            "tenant_id": oid(tenant._id),
            "receipt_no": receipt,
        })
    else:
        if receipt.startswith("GH-") and len(receipt) > 9 and receipt[9] == "-":
            maybe_tenant = receipt[:9]
            maybe_receipt = receipt[10:]
            tenant = find_tenant_by_code(maybe_tenant)
            if tenant:
                sale = mongo.db.sales.find_one({
                    "tenant_id": oid(tenant._id),
                    "receipt_no": maybe_receipt,
                })

        if sale is None:
            matches = list(mongo.db.sales.find(
                {"receipt_no": receipt},
                {"_id": 1, "tenant_id": 1, "receipt_no": 1, "total_amount": 1,
                 "timestamp": 1, "payment_method": 1, "items": 1},
            ).limit(2))
            if len(matches) == 1:
                sale = matches[0]

    if not sale:
        return jsonify({"valid": False}), 404

    return jsonify({
        "valid": True,
        "receipt_no": sale["receipt_no"],
        "total_amount": sale.get("total_amount"),
        "timestamp": sale["timestamp"].isoformat(),
        "payment_method": sale.get("payment_method"),
        "items_count": len(sale.get("items", [])),
    })