"""
Notification service.

Email   → Resend   (https://resend.com/docs/api-reference/emails/send-email)
SMS     → Arkesel  (https://sms.arkesel.com/api/v2/sms/send)
"""
import json
import base64
import requests
from flask import current_app

from extensions import mongo
from utils import oid

# ---------------------------------------------------------------------------
# Email — Resend
# ---------------------------------------------------------------------------
def send_email(to_email, subject, body_text, body_html=None, attachments=None):
    cfg = current_app.config
    api_key = cfg.get("RESEND_API_KEY")
    if not api_key:
        raise RuntimeError("Resend is not configured (RESEND_API_KEY missing)")

    payload = {
        "from": cfg.get("RESEND_FROM_EMAIL", "Pharmacole <onboarding@resend.dev>"),
        "to": [to_email],
        "subject": subject,
        "html": body_html or body_text,
        "text": body_text,
    }

    if attachments:
        payload["attachments"] = [
            {
                "filename": filename,
                "content": base64.b64encode(data).decode("ascii"),
                "content_type": mimetype,
            }
            for filename, mimetype, data in attachments
        ]

    try:
        r = requests.post(
            "https://api.resend.com/emails",
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=15,
        )
    except requests.RequestException as e:
        raise RuntimeError(f"Network error contacting Resend: {e}")

    if r.status_code >= 400:
        raise RuntimeError(f"Resend error {r.status_code}: {r.text[:300]}")

    return r.json()


def email_receipt(to_email, tenant, sale, pdf_bytes=None):
    subject = f"Receipt {sale.get('receipt_no')} — {tenant.pharmacy_name}"
    text = (
        f"Thank you for your purchase at {tenant.pharmacy_name}.\n"
        f"Receipt: {sale.get('receipt_no')}\n"
        f"Total: GH₵ {sale.get('total_amount'):.2f}\n\n"
        "See attached PDF for details."
    )
    html = (
        f"<p>Thank you for your purchase at <strong>{tenant.pharmacy_name}</strong>.</p>"
        f"<p>Receipt: <strong>{sale.get('receipt_no')}</strong><br>"
        f"Total: <strong>GH₵ {sale.get('total_amount'):.2f}</strong></p>"
    )
    
    attachments = []
    if pdf_bytes:
        attachments.append((f"{sale.get('receipt_no')}.pdf", "application/pdf", pdf_bytes))
        
    return send_email(to_email, subject, text, html, attachments)


# ---------------------------------------------------------------------------
# SMS — Arkesel (unchanged)
# ---------------------------------------------------------------------------
def _arkesel_headers():
    cfg = current_app.config
    return {
        "api-key": cfg["ARKESEL_API_KEY"],
        "Content-Type": "application/json",
    }

def send_sms(to_phone, message):
    cfg = current_app.config
    if not cfg.get("ARKESEL_API_KEY"):
        raise RuntimeError("Arkesel is not configured (ARKESEL_API_KEY missing)")

    recipient = _normalize_phone(to_phone)
    if not recipient:
        raise RuntimeError(f"Invalid phone number: {to_phone!r}")

    payload = {
        "sender": cfg["ARKESEL_SENDER_ID"],
        "message": message,
        "recipients": [recipient],
    }

    try:
        r = requests.post(
            f"{cfg['ARKESEL_BASE_URL']}/sms/send",
            json=payload,
            headers=_arkesel_headers(),
            timeout=15,
        )
    except requests.RequestException as e:
        raise RuntimeError(f"Network error contacting Arkesel: {e}")

    if r.status_code >= 400:
        raise RuntimeError(f"Arkesel error {r.status_code}: {r.text[:300]}")

    try:
        data = r.json()
    except ValueError:
        data = {}

    if str(data.get("status", "")).lower() != "success":
        raise RuntimeError(data.get("message") or "Arkesel rejected the message")

    return data

def sms_receipt(to_phone, tenant, sale):
    summary = (
        f"{tenant.pharmacy_name}\n"
        f"Receipt: {sale.get('receipt_no')}\n"
        f"Total: GH₵ {sale.get('total_amount'):.2f}\n"
        f"Paid via: {sale.get('payment_method', '').upper()}\n"
        f"Thank you!"
    )
    return send_sms(to_phone, summary)

def _normalize_phone(p):
    digits = "".join(ch for ch in str(p or "") if ch.isdigit())
    if not digits:
        return None
    if digits.startswith("233"):
        return digits
    if digits.startswith("0") and len(digits) == 10:
        return "233" + digits[1:]
    return digits


# ---------------------------------------------------------------------------
# Web Push (unchanged)
# ---------------------------------------------------------------------------
def _webpush(subscription_info, payload: dict):
    from pywebpush import webpush, WebPushException
    cfg = current_app.config
    try:
        webpush(
            subscription_info=subscription_info,
            data=json.dumps(payload),
            vapid_private_key=cfg["VAPID_PRIVATE_KEY"],
            vapid_claims={"sub": cfg["VAPID_SUBJECT"]},
        )
        return True
    except WebPushException as e:
        current_app.logger.warning("WebPush failed: %s", e)
        return False

def push_to_user(tenant_id, user_id, title, body, url=None):
    tid = oid(tenant_id)
    uid = oid(user_id)
    if not tid or not uid:
        return 0

    subs = mongo.db.push_subscriptions.find({"tenant_id": tid, "user_id": uid})
    count = 0
    for s in subs:
        info = s.get("subscription") or {}
        ok = _webpush(info, {"title": title, "body": body, "url": url or "/"})
        if ok:
            count += 1
        else:
            mongo.db.push_subscriptions.delete_one({"_id": s["_id"]})
    return count

def push_to_tenant(tenant_id, title, body, url=None, role=None):
    tid = oid(tenant_id)
    if not tid:
        return 0
    q = {"tenant_id": tid}
    if role:
        q["role"] = role
    subs = list(mongo.db.push_subscriptions.find(q))
    count = 0
    for s in subs:
        info = s.get("subscription") or {}
        ok = _webpush(info, {"title": title, "body": body, "url": url or "/"})
        if ok:
            count += 1
        else:
            mongo.db.push_subscriptions.delete_one({"_id": s["_id"]})
    return count