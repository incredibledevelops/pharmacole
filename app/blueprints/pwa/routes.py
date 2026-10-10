import json
from datetime import datetime
from flask import request, jsonify, current_app, send_from_directory
from flask_login import login_required, current_user

from . import pwa_bp
from extensions import mongo
from utils import oid


@pwa_bp.route("/pwa/manifest.json")
def manifest():
    return send_from_directory(current_app.static_folder, "manifest.json")


@pwa_bp.route("/pwa/service-worker.js")
def service_worker():
    """Service worker must be served from root scope."""
    resp = send_from_directory(current_app.static_folder, "service-worker.js")
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@pwa_bp.route("/pwa/vapid-public-key")
def vapid_key():
    return jsonify({"key": current_app.config["VAPID_PUBLIC_KEY"]})


@pwa_bp.route("/pwa/subscribe", methods=["POST"])
@login_required
def subscribe():
    data = request.get_json(silent=True) or {}
    sub = data.get("subscription")
    if not sub or not sub.get("endpoint"):
        return jsonify({"error": "subscription required"}), 400

    mongo.db.push_subscriptions.update_one(
        {"tenant_id": oid(current_user.tenant_id), "user_id": oid(current_user._id)},
        {"$set": {
            "tenant_id": oid(current_user.tenant_id),
            "user_id": oid(current_user._id),
            "role": current_user.role,
            "subscription": sub,
            "updated_at": datetime.utcnow(),
        },
           "$setOnInsert": {"created_at": datetime.utcnow()}},
        upsert=True,
    )
    return jsonify({"ok": True})


@pwa_bp.route("/pwa/unsubscribe", methods=["POST"])
@login_required
def unsubscribe():
    mongo.db.push_subscriptions.delete_one({
        "tenant_id": oid(current_user.tenant_id),
        "user_id": oid(current_user._id),
    })
    return jsonify({"ok": True})