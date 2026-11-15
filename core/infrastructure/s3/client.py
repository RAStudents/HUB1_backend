"""Filesystem development storage and S3-compatible object storage."""

import hashlib
import hmac
import logging
import os
import shutil
import time
from pathlib import Path
from urllib.parse import quote

from core.config import LOCAL_API_BASE_URL, LOCAL_HOST
from core.infrastructure.auth.tokens import jwt_secret


logger = logging.getLogger(__name__)

_DEFAULT_ORIGINS = (
    "http://localhost:8000",
    LOCAL_API_BASE_URL,
    "http://localhost:5173",
    f"http://{LOCAL_HOST}:5173",
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
    """Storage adapter. Defaults to local files; remote mode uses boto3."""

    def __init__(self,
                 endpoint: str | None = None,
                 access_key: str | None = None,
                 secret_key: str | None = None,
                 bucket: str | None = None):
        self.backend = os.getenv("S3_BACKEND", "local").strip().lower() or "local"
        if self.backend not in {"local", "s3"}:
            raise ValueError("S3_BACKEND must be 'local' or 's3'")
        self.bucket = bucket or os.getenv("S3_BUCKET", "hub").strip()
        self.storage_dir = Path(os.getenv("S3_LOCAL_DIR", "./local_s3_storage")) / self.bucket
        self._client = None

        if self.backend == "s3":
            if not self.bucket:
                raise ValueError("S3_BUCKET is required when S3_BACKEND=s3")
            try:
                import boto3
                from botocore.config import Config
            except ImportError as exc:
                raise RuntimeError("S3_BACKEND=s3 requires boto3; install it with 'pip install boto3'") from exc

            endpoint_url = endpoint or os.getenv("S3_ENDPOINT_URL", "").strip() or None
            region = os.getenv("S3_REGION", os.getenv("AWS_REGION", "us-east-1")).strip()
            access_key = access_key or os.getenv("S3_ACCESS_KEY_ID") or os.getenv("AWS_ACCESS_KEY_ID")
            secret_key = secret_key or os.getenv("S3_SECRET_ACCESS_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY")
            if bool(access_key) != bool(secret_key):
                raise ValueError("Set both S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY, or neither")
            addressing_style = os.getenv("S3_ADDRESSING_STYLE", "auto").strip().lower()
            if addressing_style not in {"auto", "virtual", "path"}:
                raise ValueError("S3_ADDRESSING_STYLE must be auto, virtual, or path")

            options = {
                "service_name": "s3",
                "region_name": region,
                "endpoint_url": endpoint_url,
                "config": Config(
                    signature_version="s3v4",
                    s3={"addressing_style": addressing_style},
                ),
            }
            # Leave credentials unset to let AWS use its standard credential chain
            # (instance/task role, environment, shared config, etc.).
            if access_key:
                options["aws_access_key_id"] = access_key
            if secret_key:
                options["aws_secret_access_key"] = secret_key
            self._client = boto3.client(**options)
            public_endpoint = os.getenv("S3_PUBLIC_ENDPOINT_URL", "").strip()
            self._presign_client = (
                boto3.client(**{**options, "endpoint_url": public_endpoint})
                if public_endpoint
                else self._client
            )
        else:
            self.storage_dir.mkdir(parents=True, exist_ok=True)
            self._presign_client = None

    @property
    def is_remote(self) -> bool:
        return self.backend == "s3"

    @staticmethod
    def validate_key(key: str) -> str:
        """Reject malformed object keys before passing them to either backend."""
        if (not isinstance(key, str) or not key or "\x00" in key
                or key.startswith(("/", "\\")) or "\\" in key):
            raise ValueError("Invalid storage key")
        if any(part in {"", ".", ".."} for part in key.split("/")):
            raise ValueError("Invalid storage key")
        return key

    def ensure_bucket(self) -> None:
        if self.is_remote:
            self._client.head_bucket(Bucket=self.bucket)
        else:
            self.storage_dir.mkdir(parents=True, exist_ok=True)

    def safe_path(self,
                  key: str) -> Path:
        key = self.validate_key(key)
        if self.is_remote:
            raise RuntimeError("Filesystem paths are unavailable for remote S3 storage")
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
        key = self.validate_key(key)
        if self.is_remote:
            self._client.put_object(
                Bucket=self.bucket, Key=key, Body=data, ContentType=content_type
            )
            return key
        file_path = self.safe_path(key)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(data)
        return key

    def get_bytes(self,
                  key: str) -> bytes | None:
        key = self.validate_key(key)
        if self.is_remote:
            try:
                response = self._client.get_object(Bucket=self.bucket, Key=key)
            except Exception as exc:
                code = getattr(exc, "response", {}).get("Error", {}).get("Code")
                if code in {"NoSuchKey", "NotFound", "404"}:
                    return None
                raise
            body = response["Body"]
            try:
                return body.read()
            finally:
                body.close()
        file_path = self.safe_path(key)
        if not file_path.is_file():
            return None
        return file_path.read_bytes()

    def delete(self,
               key: str) -> None:
        key = self.validate_key(key)
        if self.is_remote:
            self._client.delete_object(Bucket=self.bucket, Key=key)
        else:
            self.safe_path(key).unlink(missing_ok=True)

    def delete_many(self,
                    keys: list[str]) -> None:
        valid_keys = [self.validate_key(key) for key in keys if key]
        if self.is_remote:
            for start in range(0, len(valid_keys), 1000):
                batch = valid_keys[start:start + 1000]
                if batch:
                    self._client.delete_objects(
                        Bucket=self.bucket,
                        Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True},
                    )
        else:
            for key in valid_keys:
                self.delete(key)

    def delete_prefix(self,
                      prefix: str) -> None:
        # Prefixes are directory-like and callers commonly include the final slash.
        prefix = self.validate_key(prefix[:-1] if prefix.endswith("/") else prefix)
        if self.is_remote:
            paginator = self._client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=f"{prefix}/"):
                keys = [item["Key"] for item in page.get("Contents", [])]
                if keys:
                    self.delete_many(keys)
            return
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
        key = self.validate_key(key)
        if self.is_remote:
            return self._presign_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=int(expires_in),
            )
        self.safe_path(key)
        return media_url(key, base_url=base_url, expires_in=expires_in)

    def get_presigned_upload_url(self,
                                 key: str,
                                 content_type: str = "application/octet-stream",
                                 expires_in: int = 900) -> str:
        key = self.validate_key(key)
        if self.is_remote:
            return self._presign_client.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": self.bucket,
                    "Key": key,
                    "ContentType": content_type,
                },
                ExpiresIn=int(expires_in),
            )
        self.safe_path(key)
        return key
