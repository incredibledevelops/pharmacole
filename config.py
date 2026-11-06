import os
import secrets
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


def _bool(key: str, default: bool = False) -> bool:
    v = os.getenv(key)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


def _float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (TypeError, ValueError):
        return default


def _cors_origins():
    raw = os.getenv("CORS_ORIGINS", "*").strip()
    if raw == "*":
        return "*"
    return [o.strip() for o in raw.replace(",", " ").split() if o.strip()]


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY")
    PREFERRED_URL_SCHEME = os.getenv("PREFERRED_URL_SCHEME")

    MONGO_URI = os.getenv("MONGO_URI")
    MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "pharmacole")

    PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "").strip()
    PAYSTACK_PUBLIC_KEY = os.getenv("PAYSTACK_PUBLIC_KEY", "").strip()
    PAYSTACK_BASE_URL = os.getenv("PAYSTACK_BASE_URL", "https://api.paystack.co").rstrip("/")

    BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:5005").rstrip("/")

    SUBSCRIPTION_AMOUNT = _float("SUBSCRIPTION_AMOUNT", 500.0)
    SUBSCRIPTION_CURRENCY = os.getenv("SUBSCRIPTION_CURRENCY", "GHS")
    SUBSCRIPTION_DURATION_DAYS = _int("SUBSCRIPTION_DURATION_DAYS", 30)

    SUPER_ADMIN_EMAIL = os.getenv("SUPER_ADMIN_EMAIL", "").lower().strip()
    SUPER_ADMIN_PASSWORD = os.getenv("SUPER_ADMIN_PASSWORD", "")

    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", False)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
    PERMANENT_SESSION_LIFETIME = timedelta(days=_int("PERMANENT_SESSION_LIFETIME_DAYS", 7))

    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None

    RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_DEFAULT = os.getenv("RATELIMIT_DEFAULT", "1000 per day;200 per hour")
    RATELIMIT_HEADERS_ENABLED = True

    MAX_CONTENT_LENGTH = _int("MAX_CONTENT_LENGTH_MB", 8) * 1024 * 1024

    JSON_SORT_KEYS = False
    TEMPLATES_AUTO_RELOAD = _bool("FLASK_DEBUG", False)

    # ------------------------------------------------------------------
    # API / JWT
    # ------------------------------------------------------------------
    JWT_SECRET = os.getenv("JWT_SECRET")
    JWT_ALGORITHM = "HS256"
    JWT_ACCESS_TTL = timedelta(days=_int("JWT_ACCESS_TTL_DAYS", 30))
    JWT_REFRESH_TTL = timedelta(days=_int("JWT_REFRESH_TTL_DAYS", 120))
    CORS_ORIGINS = _cors_origins()

    # ------------------------------------------------------------------
    # Email — Resend (replaces SMTP)
    # ------------------------------------------------------------------
    # Leave RESEND_API_KEY empty to disable email sending (calls become no-ops).
    RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
    # Must be a verified domain on Resend. Supports "Name <email>" format,
    # e.g. "Pharmacole <receipts@pharmacole.com>".
    RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "Pharmacole <receipts@pharmacole.com>")

    # ------------------------------------------------------------------
    # SMS — Arkesel (replaces WhatsApp Cloud API)
    # ------------------------------------------------------------------
    # Leave ARKESEL_API_KEY empty to disable SMS sending (calls become no-ops).
    ARKESEL_API_KEY = os.getenv("ARKESEL_API_KEY", "").strip()
    ARKESEL_SENDER_ID = os.getenv("ARKESEL_SENDER_ID", "Pharmacole")
    ARKESEL_BASE_URL = os.getenv("ARKESEL_BASE_URL", "https://sms.arkesel.com/api/v2").rstrip("/")

    # ------------------------------------------------------------------
    # Web push (unchanged — separate from email/SMS)
    # ------------------------------------------------------------------
    VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
    VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
    VAPID_SUBJECT = os.getenv("VAPID_SUBJECT", "mailto:support@pharmacole.com")

    # Uploads
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", os.path.abspath("uploads"))
    ALLOWED_LOGO_EXT = {"png", "jpg", "jpeg", "webp", "svg"}

    # ------------------------------------------------------------------
    # Pricing tiers (unchanged)
    # ------------------------------------------------------------------
    PRICING_TIERS = {
        "starter": {
            "label": "Starter",
            "amount": 300.0,
            "branches": 1,
            "users": 2,
            "tagline": "For a single counter",
            "features": ["pos", "inventory", "expiry", "email_receipts"],
            "feature_list": [
                "Point of Sale (1 branch)",
                "Inventory & expiry tracking",
                "Up to 2 users",
                "Email receipts",
                "Basic reports",
            ],
        },
        "pro": {
            "label": "Pro",
            "amount": 500.0,
            "branches": 1,
            "users": -1,
            "tagline": "Most pharmacies",
            "features": [
                "pos", "inventory", "expiry", "email_receipts",
                "sms_receipts", "reports", "suppliers", "audit_log",
            ],
            "feature_list": [
                "Everything in Starter",
                "Unlimited users",
                "Supplier management",
                "CSV exports + shift reports",
                "SMS receipts",
                "Audit log",
            ],
            "highlight": True,
        },
        "business": {
            "label": "Business",
            "amount": 1200.0,
            "branches": 5,
            "users": -1,
            "tagline": "Growing chains",
            "features": [
                "pos", "inventory", "expiry", "email_receipts",
                "sms_receipts", "reports", "suppliers", "audit_log",
                "multi_branch", "consolidated_reports", "branding",
            ],
            "feature_list": [
                "Everything in Pro",
                "Up to 5 branches",
                "Consolidated multi-branch reports",
                "Custom branding on receipts",
                "Priority support",
            ],
        },
        "enterprise": {
            "label": "Enterprise",
            "amount": 2000.0,
            "branches": -1,
            "users": -1,
            "tagline": "Chains & franchises",
            "features": [
                "pos", "inventory", "expiry", "email_receipts",
                "sms_receipts", "reports", "suppliers", "audit_log",
                "multi_branch", "consolidated_reports", "branding",
                "api_access", "sla",
            ],
            "feature_list": [
                "Everything in Business",
                "Unlimited branches",
                "Full REST API access",
                "SLA + dedicated onboarding",
                "Custom integrations",
            ],
        },
    }

    TIER_ORDER = ["starter", "pro", "business", "enterprise"]
    API_TIERS = {"enterprise"}


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    PREFERRED_URL_SCHEME = "https"


class TestingConfig(Config):
    TESTING = True
    WTF_CSRF_ENABLED = False
    MONGO_URI = os.getenv("MONGO_URI_TEST", "mongodb://127.0.0.1:27017/pharmacole_test")
    CORS_ORIGINS = "*"


def _resolve_jwt_secret(config_obj, env: str) -> None:
    """Ensure JWT_SECRET is set. In production, refuse to boot without it."""
    secret = getattr(config_obj, "JWT_SECRET", None) or getattr(config_obj, "SECRET_KEY", None)

    if env == "production":
        if not secret or secret == "dev-only-secret-change-me":
            raise RuntimeError(
                "JWT_SECRET (or SECRET_KEY) must be set to a strong value in production. "
                "Refusing to start with an insecure secret."
            )
        config_obj.JWT_SECRET = secret
        return

    if not secret:
        secret = secrets.token_urlsafe(48)
    config_obj.JWT_SECRET = secret


def get_config():
    env = os.getenv("FLASK_ENV", "development").lower()
    if env == "production":
        cls = ProductionConfig
    elif env == "testing":
        cls = TestingConfig
    else:
        cls = DevelopmentConfig
    _resolve_jwt_secret(cls, env)
    return cls