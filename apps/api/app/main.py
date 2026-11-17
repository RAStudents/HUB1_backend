# apps/api/app/main.py

import os
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

ENV_FILE = Path(__file__).resolve().parents[3] / ".env"
if ENV_FILE.is_file():
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))

from apps.api.app.api.router import api_router
from apps.api.app.deps import get_s3_client
from core.infrastructure.s3.client import allowed_bases
from core.infrastructure.auth.tokens import assert_jwt_configured
from core.infrastructure.sql.base import init_db


logger = logging.getLogger(__name__)


_PROD = os.getenv("HUB_ENV", "dev").strip().lower() in {"prod", "production"}

app = FastAPI(
    title="HUB Dataset Annotation Platform (MVP)",
    version="1.0.0",
    docs_url=None if _PROD else "/docs",
    redoc_url=None if _PROD else "/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(allowed_bases()),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count"],
)

app.include_router(api_router)


@app.on_event("startup")
def startup_event():
    """Инициализирует БД и проверяет доступность S3 при старте приложения."""
    try:
        assert_jwt_configured()
        print("[OK] JWT_SECRET задан.")
    except Exception as exc:
        print(f"[ERROR] {exc}")
        raise

    try:
        init_db()
        print("[OK] Инициализация БД выполнена.")
    except Exception as exc:
        print(f"[ERROR] Ошибка инициализации БД при старте: {exc}")
        raise

    try:
        s3 = get_s3_client()
        s3.ensure_bucket()
        print(f"[OK] Storage ({'S3' if s3.is_remote else 'local'}) готов.")
    except Exception as exc:
        print(f"[ERROR] Не удалось проверить storage при старте: {exc}")
        if get_s3_client().is_remote:
            raise


@app.get("/health", tags=["system"])
def health_check():
    """Эндпоинт проверки работоспособности сервиса."""
    return {"status": "ok", "service": "hub-backend-mvp"}
