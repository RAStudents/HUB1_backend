# core/infrastructure/auth/passwords.py

import hashlib
import logging
import secrets


logger = logging.getLogger(__name__)


_PBKDF2_PREFIX = "pbkdf2_sha256"
_PBKDF2_ITERATIONS = 600_000
_YANDEX_MARKER = "oauth_yandex"


def hash_password(password: str) -> str:
    """Медленный парольный хэш. Один sha256 для пароля больше не используем."""
    if not isinstance(password, str) or not password:
        raise ValueError("Пароль не может быть пустым")

    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        bytes.fromhex(salt),
        _PBKDF2_ITERATIONS,
    )
    return f"{_PBKDF2_PREFIX}${_PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Проверяет и новый pbkdf2, и старые salt$sha256, пока человек не войдёт заново."""
    if not isinstance(plain_password, str) or not isinstance(hashed_password, str):
        return False
    if not plain_password or not hashed_password or hashed_password == _YANDEX_MARKER:
        return False

    try:
        if hashed_password.startswith(f"{_PBKDF2_PREFIX}$"):
            return _verify_pbkdf2(plain_password, hashed_password)
        return _verify_legacy_sha256(plain_password, hashed_password)
    except Exception:
        return False


def needs_rehash(hashed_password: str) -> bool:
    """Старый salt$sha256 надо заменить на pbkdf2 при следующем успешном входе."""
    if not isinstance(hashed_password, str) or hashed_password == _YANDEX_MARKER:
        return False
    if hashed_password.startswith(f"{_PBKDF2_PREFIX}$"):
        return False
    salt, _, expected = hashed_password.partition("$")
    return bool(salt) and bool(expected) and "$" not in expected


def _verify_pbkdf2(plain_password: str, hashed_password: str) -> bool:
    prefix, iterations, salt, expected = hashed_password.split("$", 3)
    if prefix != _PBKDF2_PREFIX:
        return False
    rounds = int(iterations)
    if rounds < 100_000 or rounds > 2_000_000:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        plain_password.encode("utf-8"),
        bytes.fromhex(salt),
        rounds,
    )
    return secrets.compare_digest(digest.hex(), expected)


def _verify_legacy_sha256(plain_password: str, hashed_password: str) -> bool:
    salt, expected = hashed_password.split("$", 1)
    if not salt or not expected:
        return False
    actual = hashlib.sha256((plain_password + salt).encode("utf-8")).hexdigest()
    return secrets.compare_digest(expected, actual)