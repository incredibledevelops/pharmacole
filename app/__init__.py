import os
from datetime import datetime
from flask import Flask, request, g, send_from_directory
from flask_login import current_user

from config import get_config
from extensions import mongo, login_manager, csrf, limiter, cors
from utils import register_jinja, oid
from models import ensure_indexes


def create_app(config_class=None):
    app = Flask(__name__, template_folder="../templates", static_folder="../static")
    app.config.from_object(config_class or get_config())

    # Extensions
    mongo.init_app(app, uri=app.config["MONGO_URI"])
    login_manager.init_app(app)
    csrf.init_app(app)

    cors.init_app(
        app,
        resources={r"/api/*": {"origins": app.config["CORS_ORIGINS"]}},
        supports_credentials=False,
        allow_headers=["Content-Type", "Authorization", "X-Device-Id"],
        methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    )

    limiter.storage_uri = app.config["RATELIMIT_STORAGE_URI"]
    limiter.default_limits = [app.config["RATELIMIT_DEFAULT"]]
    limiter.init_app(app)

    register_jinja(app)
    
    from app.services import entitlement_service
    entitlement_service.register_jinja(app)

    if not app.config.get("TESTING"):
        with app.app_context():
            try:
                ensure_indexes()
            except Exception as e:
                app.logger.warning("Index creation failed: %s", e)

    # Uploads directory + route
    uploads = os.path.abspath(app.config["UPLOAD_FOLDER"])
    os.makedirs(uploads, exist_ok=True)

    @app.route("/uploads/<path:filename>")
    def uploaded_file(filename):
        return send_from_directory(uploads, filename)

    # ------------------------------------------------------------------
    # Blueprints — register each one individually so a failure is obvious
    # ------------------------------------------------------------------
    def _reg(bp, name):
        try:
            app.register_blueprint(bp)
            app.logger.info("Registered blueprint: %s", name)
        except Exception as e:
            app.logger.error("FAILED to register blueprint %s: %s", name, e)
            raise

    from app.blueprints.auth import auth_bp
    from app.blueprints.main import main_bp
    from app.blueprints.payments import payments_bp
    from app.blueprints.webhooks import webhooks_bp
    from app.blueprints.owner import owner_bp
    from app.blueprints.pharmacist import pharmacist_bp
    from app.blueprints.cashier import cashier_bp
    from app.blueprints.super_admin import super_admin_bp

    _reg(auth_bp, "auth")
    _reg(main_bp, "main")
    _reg(payments_bp, "payments")
    _reg(webhooks_bp, "webhooks")
    _reg(owner_bp, "owner")
    _reg(pharmacist_bp, "pharmacist")
    _reg(cashier_bp, "cashier")
    _reg(super_admin_bp, "super_admin")

    # API + PWA are optional-ish: if the api submodule is broken, we want
    # the rest of the app to keep working, so we log loudly but continue.
    try:
        from app.blueprints.api import api_bp
        _reg(api_bp, "api")
    except Exception as e:
        app.logger.error("API blueprint NOT loaded: %s", e)

    try:
        from app.blueprints.pwa import pwa_bp
        _reg(pwa_bp, "pwa")
    except Exception as e:
        app.logger.error("PWA blueprint NOT loaded: %s", e)

    from app.errors import register_error_handlers
    register_error_handlers(app)

    # ------------------------------------------------------------------
    # Request context
    # ------------------------------------------------------------------
    @app.before_request
    def _attach_context():
        g.request_started = datetime.utcnow()
        g.tenant = None
        if current_user.is_authenticated and current_user.role != "super_admin":
            tid = oid(current_user.tenant_id)
            if tid:
                g.tenant = mongo.db.tenants.find_one({"_id": tid})

    # ------------------------------------------------------------------
    # Security headers
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Startup banner — prints every route so you can SEE it registered
    # ------------------------------------------------------------------
    with app.app_context():
        try:
            rules = sorted(
                [(r.rule, ",".join(sorted(r.methods - {"HEAD", "OPTIONS"}))) for r in app.url_map.iter_rules()]
            )
            app.logger.info("---- URL MAP (%d rules) ----", len(rules))
            for rule, methods in rules:
                if rule.startswith("/api/") or rule.startswith("/pwa/") or rule == "/healthz":
                    app.logger.info("  %-45s %s", rule, methods)
            app.logger.info("----------------------------")
        except Exception:
            pass

    return app