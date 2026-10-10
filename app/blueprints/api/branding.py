import os
import uuid
from flask import request, jsonify, g, current_app
from werkzeug.utils import secure_filename

from . import api_bp
from decorators import token_required, api_role_required, api_subscription_required
from app.services import tenant_service, audit_service


def _allowed(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower()
        in current_app.config["ALLOWED_LOGO_EXT"]
    )


@api_bp.route("/branding", methods=["GET"])
@token_required
def get_branding():
    t = g.api_tenant
    if not t:
        return jsonify({"error": "No tenant"}), 404
    return jsonify({
        "logo_url": t.logo_url,
        "receipt_header": t.receipt_header,
        "receipt_footer": t.receipt_footer,
        "tin": t.tin,
        "business_reg_no": t.business_reg_no,
        "pharmacy_name": t.pharmacy_name,
        "address": t.address,
    })


@api_bp.route("/branding", methods=["PATCH"])
@token_required
@api_role_required("owner")
@api_subscription_required
def update_branding():
    data = request.get_json(silent=True) or {}
    ok = tenant_service.update_branding(
        g.api_user.tenant_id,
        logo_url=data.get("logo_url"),
        receipt_header=data.get("receipt_header"),
        receipt_footer=data.get("receipt_footer"),
        tin=data.get("tin"),
        business_reg_no=data.get("business_reg_no"),
    )
    audit_service.log("branding.update", meta={k: v for k, v in data.items() if v is not None})
    return jsonify({"ok": ok})


@api_bp.route("/branding/logo", methods=["POST"])
@token_required
@api_role_required("owner")
@api_subscription_required
def upload_logo():
    if "file" not in request.files:
        return jsonify({"error": "No file"}), 400
    f = request.files["file"]
    if not f or not f.filename:
        return jsonify({"error": "Empty filename"}), 400
    if not _allowed(f.filename):
        return jsonify({"error": "Invalid file type"}), 400

    ext = f.filename.rsplit(".", 1)[1].lower()
    fname = secure_filename(f"{uuid.uuid4().hex}.{ext}")
    folder = os.path.join(current_app.config["UPLOAD_FOLDER"], "logos")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, fname)
    f.save(path)

    # Public URL served by Flask /static/uploads -> mount it in create_app
    logo_url = f"{current_app.config['BASE_URL']}/uploads/logos/{fname}"
    tenant_service.update_branding(g.api_user.tenant_id, logo_url=logo_url)
    audit_service.log("branding.logo_upload", meta={"logo_url": logo_url})
    return jsonify({"ok": True, "logo_url": logo_url})