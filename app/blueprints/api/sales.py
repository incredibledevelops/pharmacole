from flask import request, jsonify, g
from datetime import datetime, timedelta

from . import api_bp
from decorators import token_required, api_role_required, api_subscription_required
from app.services import sales_service


@api_bp.route("/sales/checkout", methods=["POST"])
@token_required
@api_role_required("cashier", "owner", "pharmacist")
@api_subscription_required
def checkout():
    data = request.get_json(silent=True) or {}
    items = data.get("items") or []
    method = (data.get("payment_method") or "").strip().lower()
    client_uuid = data.get("client_uuid")
    branch_id = data.get("branch_id") or g.api_user.branch_id
    customer_name = data.get("customer_name")
    discount = data.get("discount", 0.0)

    try:
        receipt = sales_service.record_sale(
            tenant_id=g.api_user.tenant_id,
            cashier=g.api_user,
            items=items,
            payment_method=method,
            branch_id=branch_id,
            client_uuid=client_uuid,
            customer_name=customer_name,
            discount=discount,
        )
    except sales_service.IdempotentReplay as replay:
        return jsonify(sales_service._sale_to_dict(replay.existing)), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    # Optional automatic delivery: "email", "sms", or "both".
    deliver = (data.get("deliver") or "").lower()
    customer_email = data.get("customer_email")
    customer_phone = data.get("customer_phone")

    if deliver in ("email", "both") and customer_email:
        try:
            _email_receipt(customer_email, receipt)
        except Exception as e:
            receipt["email_error"] = str(e)

    if deliver in ("sms", "both") and customer_phone:
        try:
            _sms_receipt(customer_phone, receipt)
        except Exception as e:
            receipt["sms_error"] = str(e)

    return jsonify(receipt), 200


@api_bp.route("/sales", methods=["GET"])
@token_required
@api_subscription_required
def list_sales():
    try:
        limit = int(request.args.get("limit", 200))
    except (TypeError, ValueError):
        limit = 200
    branch_id = request.args.get("branch_id")
    days = request.args.get("days")
    since = None
    if days:
        try:
            since = datetime.utcnow() - timedelta(days=int(days))
        except (TypeError, ValueError):
            since = None

    rows = sales_service.list_for_tenant(
        g.api_user.tenant_id, limit=min(limit, 2000),
        since=since, branch_id=branch_id,
    )
    out = []
    for s in rows:
        out.append({
            "receipt_no": s["receipt_no"],
            "timestamp": s["timestamp"].isoformat(),
            "cashier_name": s.get("cashier_name"),
            "items": [{"name": i["name"], "qty": i["qty"],
                       "line_subtotal": i["line_subtotal"]} for i in s.get("items", [])],
            "subtotal": s.get("subtotal"),
            "vat": s.get("vat"),
            "discount": s.get("discount", 0.0),
            "total_amount": s.get("total_amount"),
            "payment_method": s.get("payment_method"),
            "branch_id": str(s["branch_id"]) if s.get("branch_id") else None,
        })
    return jsonify({"items": out})


@api_bp.route("/sales/today", methods=["GET"])
@token_required
@api_subscription_required
def today():
    branch_id = request.args.get("branch_id")
    return jsonify({
        "revenue": sales_service.revenue_today(g.api_user.tenant_id, branch_id=branch_id),
    })


@api_bp.route("/sales/sync", methods=["POST"])
@token_required
@api_role_required("cashier", "owner", "pharmacist")
@api_subscription_required
def sync_offline():
    """Accept a batch of offline sales. Each must carry a client_uuid."""
    data = request.get_json(silent=True) or {}
    batch = data.get("sales") or []
    results = []

    for row in batch:
        client_uuid = (row.get("client_uuid") or "").strip()
        if not client_uuid:
            results.append({
                "client_uuid": None,
                "ok": False,
                "error": "client_uuid is required for offline sync",
            })
            continue
        try:
            r = sales_service.record_sale(
                tenant_id=g.api_user.tenant_id,
                cashier=g.api_user,
                items=row.get("items") or [],
                payment_method=(row.get("payment_method") or "").strip().lower(),
                branch_id=row.get("branch_id") or g.api_user.branch_id,
                client_uuid=client_uuid,
                customer_name=row.get("customer_name"),
                discount=row.get("discount", 0.0),
            )
            results.append({"client_uuid": client_uuid, "ok": True,
                            "receipt_no": r["receipt_no"]})
        except sales_service.IdempotentReplay as replay:
            results.append({
                "client_uuid": client_uuid,
                "ok": True,
                "receipt_no": replay.existing["receipt_no"],
                "idempotent": True,
            })
        except Exception as e:
            results.append({"client_uuid": client_uuid, "ok": False,
                            "error": str(e)})

    return jsonify({"results": results}), 200


# ---------------------------------------------------------------------------
# helper functions
# ---------------------------------------------------------------------------

def _email_receipt(to_email, receipt_dict):
    from models import find_tenant_by_id
    from app.services import receipt_service, notification_service
    tenant = find_tenant_by_id(g.api_user.tenant_id)
    sale = _sale_dict_for_receipt(receipt_dict)
    pdf = None
    try:
        pdf = receipt_service.receipt_pdf(tenant, sale)
    except Exception:
        pdf = None
    notification_service.email_receipt(to_email, tenant, sale, pdf_bytes=pdf)


def _sms_receipt(to_phone, receipt_dict):
    from models import find_tenant_by_id
    from app.services import notification_service
    tenant = find_tenant_by_id(g.api_user.tenant_id)
    sale = _sale_dict_for_receipt(receipt_dict)
    notification_service.sms_receipt(to_phone, tenant, sale)


def _sale_dict_for_receipt(r):
    return {
        "receipt_no": r.get("receipt_no"),
        "timestamp": r.get("timestamp") or datetime.utcnow().isoformat(),
        "cashier_name": g.api_user.name,
        "items": r.get("items", []),
        "subtotal": r.get("subtotal", 0.0),
        "vat": r.get("vat", 0.0),
        "discount": r.get("discount", 0.0),
        "total_amount": r.get("total") or r.get("total_amount"),
        "payment_method": r.get("payment_method"),
    }