# core/infrastructure/auth/tokens.py

import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt


logger = logging.getLogger(__name__)


ALGORITHM = "HS256"
ISSUER = "hub"
AUDIENCE = "hub-api"
_FORBIDDEN_SECRETS = {
    "super_secret_hub_key",
    "changeme",
    "secret",
    "password",
    "jwt_secret",
}
_MAX_TOKEN_LENGTH = 4096


def jwt_secret() -> str:
    """Секрет только из окружения. Дефолта нет: иначе токен можно подписать вслепую."""
    secret = os.getenv("JWT_SECRET", "").strip()
    if len(secret) < 32 or secret.lower() in _FORBIDDEN_SECRETS:
        raise RuntimeError(
            "JWT_SECRET не задан или слишком слабый. "
            'Сгенерируйте: python -c "import secrets; print(secrets.token_hex(32))" '
            "и положите в .env. Минимум 32 символа, не используйте super_secret_hub_key."
        )
    return secret


def assert_jwt_configured() -> None:
    jwt_secret()


def access_ttl() -> timedelta:
    minutes = int(os.getenv("JWT_ACCESS_TTL_MINUTES", "15"))
    if not 1 <= minutes <= 60:
        raise RuntimeError("JWT_ACCESS_TTL_MINUTES должен быть от 1 до 60")
    return timedelta(minutes=minutes)


def refresh_ttl() -> timedelta:
    days = int(os.getenv("JWT_REFRESH_TTL_DAYS", "14"))
    if not 1 <= days <= 30:
        raise RuntimeError("JWT_REFRESH_TTL_DAYS должен быть от 1 до 30")
    return timedelta(days=days)


def create_access_token(user_id: int) -> tuple[str, str, datetime]:
    """Короткий JWT. Возвращает сам токен, его jti и момент истечения."""
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id <= 0:
        raise ValueError("user_id должен быть положительным int")

    now = datetime.now(timezone.utc)
    expires_at = now + access_ttl()
    jti = uuid4().hex
    payload = {
        "sub": str(user_id),
        "iat": now,
        "nbf": now,
        "exp": expires_at,
        "iss": ISSUER,
        "aud": AUDIENCE,
        "jti": jti,
        "typ": "access",
    }
    token = jwt.encode(payload, jwt_secret(), algorithm=ALGORITHM)
    return token, jti, expires_at


def decode_access_claims(token: str) -> dict | None:
    """
    Проверяет подпись, срок, iss/aud и typ=access.
    Refresh сюда не проходит: это не JWT, а отдельная случайная строка.
    """
    if not isinstance(token, str) or not token or len(token) > _MAX_TOKEN_LENGTH:
        return None
    if token.count(".") != 2:
        return None

    try:
        payload = jwt.decode(
            token,
            jwt_secret(),
            algorithms=[ALGORITHM],
            audience=AUDIENCE,
            issuer=ISSUER,
            leeway=10,
            options={
                "require": ["exp", "iat", "nbf", "sub", "jti", "typ", "iss", "aud"],
            },
        )
    except Exception:
        return None

    if payload.get("typ") != "access":
        return None

    subject = payload.get("sub")
    if not isinstance(subject, str) or not subject.isdigit() or int(subject) <= 0:
        return None
    if not isinstance(payload.get("jti"), str) or not payload["jti"]:
        return None
    return payload


def decode_access_token(token: str) -> int | None:
    """Совместимость со старым вызовом: только user_id, без проверки отзыва."""
    claims = decode_access_claims(token)
    if claims is None:
        return None
    return int(claims["sub"])


def new_refresh_token() -> str:
    """Непрозрачный refresh. В JWT его не кладём и секретом не подписываем."""
    return secrets.token_urlsafe(32)


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_family_id() -> str:
    return secrets.token_hex(16)