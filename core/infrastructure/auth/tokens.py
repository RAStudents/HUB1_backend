# core/infrastructure/auth/tokens.py
import os
import jwt
from datetime import datetime, timedelta, timezone

SECRET_KEY = os.getenv("JWT_SECRET", "super_secret_hub_key")
ALGORITHM = "HS256"
DEFAULT_TTL = timedelta(days=7)


def create_access_token(user_id: int, expires_delta: timedelta = DEFAULT_TTL) -> str:
    """Создаёт подписанный JWT с идентификатором пользователя."""
    expire = datetime.now(timezone.utc) + expires_delta
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> int | None:
    """Декодирует JWT и возвращает user_id, или None если токен недействителен."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id_str = payload.get("sub")
        return int(user_id_str) if user_id_str else None
    except Exception:
        return None
