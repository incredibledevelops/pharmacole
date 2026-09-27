import os
from datetime import datetime
from flask import Flask, request, g
from flask_login import current_user

from config import get_config
from extensions import mongo, login_manager, csrf, limiter
from utils import register_jinja, oid
from models import ensure_indexes


def create_app(config_class=None):
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config.from_object(config_class or get_config())

    # Init extensions
    mongo.init_app(app, uri=app.config["MONGO_URI"])
    login_manager.init_app(app)
    csrf.init_app(app)

    limiter.storage_uri = app.config["RATELIMIT_STORAGE_URI"]
    limiter.default_limits = [app.config["RATELIMIT_DEFAULT"]]
    limiter.init_app(app)

    # Register Jinja helpers
    register_jinja(app)

    # Ensure indexes (once per process)
    if not app.config.get("TESTING"):
        with app.app_context():
            try:
                ensure_indexes()
            except Exception as e:
                app.logger.warning("Index creation failed: %s", e)

    # Blueprints
    from app.blueprints.auth import auth_bp
    from app.blueprints.main import main_bp
    from app.blueprints.payments import payments_bp
    from app.blueprints.webhooks import webhooks_bp
    from app.blueprints.owner import owner_bp
    from app.blueprints.pharmacist import pharmacist_bp
    from app.blueprints.cashier import cashier_bp
    from app.blueprints.super_admin import super_admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(payments_bp)
    app.register_blueprint(webhooks_bp)
    app.register_blueprint(owner_bp)
    app.register_blueprint(pharmacist_bp)
    app.register_blueprint(cashier_bp)
    app.register_blueprint(super_admin_bp)

    # Error handlers
    from app.errors import register_error_handlers
    register_error_handlers(app)

    # Request context — attach tenant + request start time
    @app.before_request
    def _attach_context():
        g.request_started = datetime.utcnow()
        g.tenant = None
        if current_user.is_authenticated and current_user.role != "super_admin":
            tid = oid(current_user.tenant_id)
            if tid:
                g.tenant = mongo.db.tenants.find_one({"_id": tid})

    # Security headers
    @app.after_request
    def _security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), microphone=(), camera=()",
        )
        if not app.config.get("DEBUG"):
            resp.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return resp

    return app