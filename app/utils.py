from datetime import datetime, date, timezone
from bson import ObjectId
from bson.errors import InvalidId


# ---------------------------------------------------------------------------
# Formatting filters
# ---------------------------------------------------------------------------

def ghs(value):
    """Format a number as Ghana cedis."""
    try:
        return f"GH₵ {float(value):,.2f}"
    except (TypeError, ValueError):
        return "GH₵ 0.00"


def _coerce_dt(value):
    """Best-effort conversion of value to datetime. Returns None on failure."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        for fmt in (
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
        ):
            try:
                return datetime.strptime(s.replace("Z", ""), fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(s.replace("Z", ""))
        except Exception:
            return None
    return None


def iso_or_str(value):
    """Safely return an ISO 8601 string. None → ''."""
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    return str(value)


# Public alias: templates can use `|as_dt` and it resolves to the same
# function the rest of the codebase already relies on.
as_dt = _coerce_dt


def nice_date(value):
    dt = _coerce_dt(value)
    if not dt:
        return "—"
    return dt.strftime("%b %d, %Y")


def nice_datetime(value):
    dt = _coerce_dt(value)
    if not dt:
        return "—"
    return dt.strftime("%b %d, %Y · %H:%M")


def nice_time(value):
    dt = _coerce_dt(value)
    if not dt:
        return "—"
    return dt.strftime("%H:%M")


def days_until(value):
    """
    Integer days until value, or None when unknown.

    Returning None (not a magic 9999) lets templates distinguish "no date"
    from "far future". The existing template filters already render "—"
    for None via `nice_date`.
    """
    dt = _coerce_dt(value)
    if not dt:
        return None
    return (dt.date() - datetime.utcnow().date()).days


# ---------------------------------------------------------------------------
# Tenant helpers (work with Tenant object OR raw dict)
# ---------------------------------------------------------------------------

def _tget(tenant, key, default=None):
    if tenant is None:
        return default
    if hasattr(tenant, key):
        v = getattr(tenant, key, None)
        if v is not None:
            return v
    if isinstance(tenant, dict):
        return tenant.get(key, default)
    data = getattr(tenant, "data", None)
    if isinstance(data, dict):
        return data.get(key, default)
    return default


def t_name(tenant):
    return _tget(tenant, "pharmacy_name") or "Pharmacy"


def t_code(tenant):
    return _tget(tenant, "tenant_code") or "—"


def t_initials(tenant):
    name = t_name(tenant)
    parts = [w for w in name.split() if w]
    return "".join([w[0] for w in parts[:2]]).upper() or "PH"


def t_status(tenant):
    return _tget(tenant, "subscription_status") or "unknown"


def t_expires(tenant):
    return _tget(tenant, "subscription_expires_at")


def t_amount(tenant):
    """
    Tier-aware default. Previously fell back to the old hardcoded 500.00,
    which is now only correct for the Pro plan. Read the tenant's tier
    from PRICING_TIERS when possible.
    """
    v = _tget(tenant, "subscription_amount")
    try:
        if v is not None:
            return float(v)
    except (TypeError, ValueError):
        pass

    # Fall back to the tier's configured amount.
    tier = _tget(tenant, "tier")
    if tier:
        try:
            from flask import current_app
            tiers = current_app.config.get("PRICING_TIERS", {})
            if tier in tiers:
                return float(tiers[tier].get("amount", 0.0))
        except Exception:
            pass
    return 0.0


# ---------------------------------------------------------------------------
# ObjectId helpers
# ---------------------------------------------------------------------------

def oid(value):
    """Return ObjectId or None on invalid input."""
    if isinstance(value, ObjectId):
        return value
    if not value:
        return None
    try:
        return ObjectId(str(value))
    except (InvalidId, TypeError):
        return None


# ---------------------------------------------------------------------------
# Number parsing
# ---------------------------------------------------------------------------

def to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def to_int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Jinja registration
# ---------------------------------------------------------------------------

def register_jinja(app):
    # Formatting filters
    app.jinja_env.filters["ghs"] = ghs
    app.jinja_env.filters["nice_date"] = nice_date
    app.jinja_env.filters["nice_datetime"] = nice_datetime
    app.jinja_env.filters["nice_time"] = nice_time
    app.jinja_env.filters["days_until"] = days_until

    # Safe date filters
    app.jinja_env.filters["iso_or_str"] = iso_or_str
    app.jinja_env.filters["as_dt"] = as_dt

    # Context globals
    app.jinja_env.globals.update(
        t_name=t_name,
        t_code=t_code,
        t_initials=t_initials,
        t_status=t_status,
        t_expires=t_expires,
        t_amount=t_amount,
        now=lambda: datetime.utcnow(),
        now_utc=datetime.utcnow,
    )


# ---------------------------------------------------------------------------
# Device / audit helpers
# ---------------------------------------------------------------------------

def client_ip(request):
    """Best-effort client IP behind nginx / cloudflare."""
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.remote_addr or "unknown"


def device_fingerprint(request):
    """Light-weight fingerprint for audit logs — no persistence needed."""
    import hashlib
    parts = [
        request.headers.get("User-Agent", ""),
        request.headers.get("Accept-Language", ""),
        request.headers.get("X-Device-Id", ""),   # electron/pwa can send this
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]


def is_api_request(request):
    return request.path.startswith("/api/")