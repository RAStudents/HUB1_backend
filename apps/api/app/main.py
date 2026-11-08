# apps/api/app/main.py

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

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
from core.infrastructure.sql.base import init_db


logger = logging.getLogger(__name__)


app = FastAPI(
    title="HUB Dataset Annotation Platform (MVP)",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Раздача статических файлов (превью и маски)
STORAGE_DIR = Path("storage")
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/storage", StaticFiles(directory=str(STORAGE_DIR)), name="storage")

# CORS для фронтенда
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.on_event("startup")
def startup_event():
    """Инициализирует БД и проверяет доступность S3 при старте приложения."""
    try:
        init_db()
        print("[OK] Инициализация БД выполнена.")
    except Exception as exc:
        print(f"[ERROR] Ошибка инициализации БД при старте: {exc}")

    try:
        s3 = get_s3_client()
        s3.ensure_bucket()
        print("[OK] S3 (MinIO) подключен, бакет готов.")
    except Exception as exc:
        print(f"[WARNING] Не удалось подключиться к S3 при старте: {exc}")


@app.get("/health", tags=["system"])
def health_check():
    """Эндпоинт проверки работоспособности сервиса."""
    return {"status": "ok", "service": "hub-backend-mvp"}
