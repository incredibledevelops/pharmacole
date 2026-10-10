import smtplib
import ssl
from email.message import EmailMessage
from datetime import datetime

import requests
from flask import current_app

from extensions import mongo
from utils import oid


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def send_email(to_email, subject, body_text, body_html=None, attachments=None):
    cfg = current_app.config
    if not cfg.get("SMTP_HOST") or not cfg.get("SMTP_USER"):
        raise RuntimeError("SMTP not configured")

    msg = EmailMessage()
    msg["From"] = cfg["SMTP_FROM"]
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body_text)
    if body_html:
        msg.add_alternative(body_html, subtype="html")

    for filename, mimetype, data in (attachments or []):
        maintype, _, subtype = mimetype.partition("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)

    ctx = ssl.create_default_context()
    if cfg["SMTP_USE_TLS"]:
        with smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"]) as s:
            s.starttls(context=ctx)
            s.login(cfg["SMTP_USER"], cfg["SMTP_PASS"])
            s.send_message(msg)
    else:
        with smtplib.SMTP_SSL(cfg["SMTP_HOST"], cfg["SMTP_PORT"], context=ctx) as s:
            s.login(cfg["SMTP_USER"], cfg["SMTP_PASS"])
            s.send_message(msg)
    return True


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
# WhatsApp Cloud API
# ---------------------------------------------------------------------------

def _wa_headers():
    cfg = current_app.config
    return {
        "Authorization": f"Bearer {cfg['WHATSAPP_TOKEN']}",
        "Content-Type": "application/json",
    }


def send_whatsapp_text(to_phone, message):
    cfg = current_app.config
    if not cfg.get("WHATSAPP_TOKEN") or not cfg.get("WHATSAPP_PHONE_ID"):
        raise RuntimeError("WhatsApp not configured")

    url = f"{cfg['WHATSAPP_API_URL']}/{cfg['WHATSAPP_PHONE_ID']}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": _normalize_phone(to_phone),
        "type": "text",
        "text": {"body": message},
    }
    r = requests.post(url, json=payload, headers=_wa_headers(), timeout=15)
    if r.status_code >= 400:
        raise RuntimeError(f"WhatsApp error {r.status_code}: {r.text[:200]}")
    return r.json()


def send_whatsapp_document(to_phone, pdf_url_or_id, filename, caption=None):
    cfg = current_app.config
    if not cfg.get("WHATSAPP_TOKEN") or not cfg.get("WHATSAPP_PHONE_ID"):
        raise RuntimeError("WhatsApp not configured")

    url = f"{cfg['WHATSAPP_API_URL']}/{cfg['WHATSAPP_PHONE_ID']}/messages"
    doc = {"link": pdf_url_or_id, "filename": filename}
    if caption:
        doc["caption"] = caption
    payload = {
        "messaging_product": "whatsapp",
        "to": _normalize_phone(to_phone),
        "type": "document",
        "document": doc,
    }
    r = requests.post(url, json=payload, headers=_wa_headers(), timeout=20)
    if r.status_code >= 400:
        raise RuntimeError(f"WhatsApp error {r.status_code}: {r.text[:200]}")
    return r.json()


def whatsapp_receipt(to_phone, tenant, sale):
    summary = (
        f"*{tenant.pharmacy_name}*\n"
        f"Receipt: {sale.get('receipt_no')}\n"
        f"Total: GH₵ {sale.get('total_amount'):.2f}\n"
        f"Paid via: {sale.get('payment_method','').upper()}\n"
        f"Thank you!"
    )
    return send_whatsapp_text(to_phone, summary)


def _normalize_phone(p):
    """Turn 024xxxxxxx into 23324xxxxxxx for WhatsApp."""
    digits = "".join(ch for ch in str(p or "") if ch.isdigit())
    if digits.startswith("0") and len(digits) == 10:
        return "233" + digits[1:]
    if digits.startswith("233"):
        return digits
    return digits


# ---------------------------------------------------------------------------
# Web Push (VAPID)
# ---------------------------------------------------------------------------

def _webpush(subscription_info, payload: dict):
    from pywebpush import webpush, WebPushException
    cfg = current_app.config
    try:
        webpush(
            subscription_info=subscription_info,
            data=__import__("json").dumps(payload),
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
            # prune dead subscription
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