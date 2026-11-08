# core/infrastructure/auth/passwords.py

import hashlib
import secrets
import logging


logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    """Хэширует пароль с солью (sha256 + hex-соль)."""
    salt = secrets.token_hex(16)
    pwd_hash = hashlib.sha256((password + salt).encode("utf-8")).hexdigest()
    return f"{salt}${pwd_hash}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Проверяет пароль против сохранённого хэша. Возвращает False при любой ошибке."""
    try:
        salt, pwd_hash = hashed_password.split("$")
        check_hash = hashlib.sha256((plain_password + salt).encode("utf-8")).hexdigest()
        return secrets.compare_digest(pwd_hash, check_hash)
    except Exception:
        return False
