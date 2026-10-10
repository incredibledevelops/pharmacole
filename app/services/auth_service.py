import jwt
from datetime import datetime
from flask import current_app

from models import find_user_by_email, User


class TokenError(Exception):
    pass


def _now():
    return datetime.utcnow()


def issue_tokens(user: User) -> dict:
    """Return {access, refresh, expires_in, user}. Uses `get_id()` so
    password changes invalidate old tokens (session_version)."""
    secret = current_app.config["JWT_SECRET"]
    alg = current_app.config["JWT_ALGORITHM"]
    access_ttl = current_app.config["JWT_ACCESS_TTL"]
    refresh_ttl = current_app.config["JWT_REFRESH_TTL"]

    sub = user.get_id()  # "hex:version"

    access_payload = {
        "sub": sub,
        "role": user.role,
        "tenant_id": user.tenant_id,
        "branch_id": user.branch_id,
        "type": "access",
        "iat": int(_now().timestamp()),
        "exp": int((_now() + access_ttl).timestamp()),
    }
    refresh_payload = {
        "sub": sub,
        "type": "refresh",
        "iat": int(_now().timestamp()),
        "exp": int((_now() + refresh_ttl).timestamp()),
    }

    return {
        "access": jwt.encode(access_payload, secret, algorithm=alg),
        "refresh": jwt.encode(refresh_payload, secret, algorithm=alg),
        "expires_in": int(access_ttl.total_seconds()),
        "token_type": "Bearer",
        "user": {
            "id": user._id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "tenant_id": user.tenant_id,
            "branch_id": user.branch_id,
        },
    }


def decode_token(token: str, expected_type: str = "access") -> dict:
    secret = current_app.config["JWT_SECRET"]
    alg = current_app.config["JWT_ALGORITHM"]
    try:
        payload = jwt.decode(token, secret, algorithms=[alg])
    except jwt.ExpiredSignatureError:
        raise TokenError("Token expired")
    except jwt.InvalidTokenError:
        raise TokenError("Invalid token")

    if payload.get("type") != expected_type:
        raise TokenError("Wrong token type")
    return payload


def authenticate(email: str, password: str):
    user = find_user_by_email(email)
    if not user or not user.check_password(password):
        return None
    if not user.is_active:
        return None
    return user