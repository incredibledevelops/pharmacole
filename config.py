import os
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


class Config:
    # ---------- Flask ----------
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    PREFERRED_URL_SCHEME = os.getenv("PREFERRED_URL_SCHEME", "http")

    # ---------- MongoDB ----------
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017/pharmacole")
    MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "pharmacole")

    # ---------- Paystack ----------
    PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "").strip()
    PAYSTACK_PUBLIC_KEY = os.getenv("PAYSTACK_PUBLIC_KEY", "").strip()
    PAYSTACK_BASE_URL = os.getenv("PAYSTACK_BASE_URL", "https://api.paystack.co").rstrip("/")

    # ---------- App URL ----------
    BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:5005").rstrip("/")

    # ---------- Subscription ----------
    SUBSCRIPTION_AMOUNT = _float("SUBSCRIPTION_AMOUNT", 500.0)
    SUBSCRIPTION_CURRENCY = os.getenv("SUBSCRIPTION_CURRENCY", "GHS")
    SUBSCRIPTION_DURATION_DAYS = _int("SUBSCRIPTION_DURATION_DAYS", 30)

    # ---------- Super admin seed ----------
    SUPER_ADMIN_EMAIL = os.getenv("SUPER_ADMIN_EMAIL", "admin@pharmacole.com").lower().strip()
    SUPER_ADMIN_PASSWORD = os.getenv("SUPER_ADMIN_PASSWORD", "changeme123")

    # ---------- Session cookies ----------
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", False)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "Lax")
    PERMANENT_SESSION_LIFETIME = timedelta(days=_int("PERMANENT_SESSION_LIFETIME_DAYS", 7))

    # ---------- CSRF ----------
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = None  # tied to session lifetime

    # ---------- Rate limiting ----------
    RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_DEFAULT = os.getenv("RATELIMIT_DEFAULT", "200 per hour")
    RATELIMIT_HEADERS_ENABLED = True

    # ---------- Uploads / size ----------
    MAX_CONTENT_LENGTH = _int("MAX_CONTENT_LENGTH_MB", 8) * 1024 * 1024

    # ---------- Misc ----------
    JSON_SORT_KEYS = False
    TEMPLATES_AUTO_RELOAD = _bool("FLASK_DEBUG", False)


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


def get_config():
    env = os.getenv("FLASK_ENV", "development").lower()
    if env == "production":
        return ProductionConfig
    if env == "testing":
        return TestingConfig
    return DevelopmentConfig