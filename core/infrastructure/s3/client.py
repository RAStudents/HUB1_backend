# core/infrastructure/s3/client.py

import os
import time
import hmac
import shutil
import hashlib
import logging

from pathlib import Path
from urllib.parse import quote

from core.infrastructure.auth.tokens import jwt_secret


logger = logging.getLogger(__name__)

_DEFAULT_ORIGINS = (
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


def allowed_bases() -> set[str]:
    configured = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    origins = [
        item.strip().rstrip("/")
        for item in os.getenv("CORS_ORIGINS", "").split(",")
        if item.strip()
    ]
    bases = set(_DEFAULT_ORIGINS)
    bases.update(origins)
    if configured:
        bases.add(configured)
    return bases


def public_base(passed: str = "") -> str:
    """Не берём произвольный Host. Пустое значение = относительная ссылка."""
    configured = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if configured:
        return configured
    candidate = (passed or "").strip().rstrip("/")
    if candidate in allowed_bases():
        return candidate
    return ""


def media_url(key: str,
              base_url: str = "",
              expires_in: int = 3600) -> str:
    expires_at = int(time.time()) + int(expires_in)
    signature = sign_media(key, expires_at)
    path = f"/api/media?key={quote(key, safe='')}&exp={expires_at}&sig={signature}"
    base = public_base(base_url)
    return f"{base}{path}" if base else path


def sign_media(key: str,
               expires_at: int) -> str:
    message = f"{key}\n{int(expires_at)}".encode("utf-8")
    return hmac.new(jwt_secret().encode("utf-8"), message, hashlib.sha256).hexdigest()


def media_signature_ok(key: str,
                       expires_at: int,
                       signature: str) -> bool:
    if not isinstance(signature, str) or not expires_at:
        return False
    if int(expires_at) < int(time.time()):
        return False
    expected = sign_media(key, int(expires_at))
    return hmac.compare_digest(expected, signature)


class S3Client:
    """Локальная заглушка хранилища. Путь всегда остаётся внутри корня бакета."""

    def __init__(self,
                 endpoint: str | None = None,
                 access_key: str | None = None,
                 secret_key: str | None = None,
                 bucket: str = "hub"):
        self.bucket = bucket
        self.storage_dir = Path("./local_s3_storage") / bucket
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def ensure_bucket(self) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def safe_path(self,
                  key: str) -> Path:
        if not isinstance(key, str) or not key or key.startswith(("/", "\\")):
            raise ValueError("Invalid storage key")
        relative = Path(key)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Invalid storage key")
        root = self.storage_dir.resolve()
        target = (root / relative).resolve()
        if not target.is_relative_to(root):
            raise ValueError("Invalid storage key")
        return target

    def put_bytes(self,
                  key: str,
                  data: bytes,
                  content_type: str = "application/octet-stream") -> str:
        file_path = self.safe_path(key)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(data)
        return key

    def get_bytes(self,
                  key: str) -> bytes | None:
        file_path = self.safe_path(key)
        if not file_path.is_file():
            return None
        return file_path.read_bytes()

    def delete(self,
               key: str) -> None:
        self.safe_path(key).unlink(missing_ok=True)

    def delete_many(self,
                    keys: list[str]) -> None:
        for key in keys:
            if key:
                self.delete(key)

    def delete_prefix(self,
                      prefix: str) -> None:
        target = self.safe_path(prefix)
        root = self.storage_dir.resolve()
        if target == root:
            raise ValueError("Invalid storage prefix")
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()

    def get_presigned_url(self,
                          key: str,
                          expires_in: int = 3600,
                          base_url: str = "") -> str:
        self.safe_path(key)
        return media_url(key, base_url=base_url, expires_in=expires_in)

    def get_presigned_upload_url(self,
                                 key: str,
                                 content_type: str = "application/octet-stream",
                                 expires_in: int = 900) -> str:
        self.safe_path(key)
        return key