import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.app.api.router import api_router
from apps.api.app.deps import get_s3_client
from core.infrastructure.sql.base import init_db
from fastapi.staticfiles import StaticFiles



app = FastAPI(
    title="HUB Dataset Annotation Platform (MVP)",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

STORAGE_DIR = "storage"
os.makedirs(STORAGE_DIR, exist_ok=True)
app.mount("/storage", StaticFiles(directory=STORAGE_DIR), name="storage")

# Настройка CORS для фронтенда
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Подключаем общий API-роутер
app.include_router(api_router)


@app.on_event("startup")
def startup_event():
    """Действия при старте приложения: проверка/создание S3 бакета."""
    s3 = get_s3_client()
    try:
        s3.ensure_bucket()
        print("✅ Успешное подключение к S3 (MinIO), бакет готов к работе.")
    except Exception as exc:
        print(f"⚠️ Внимание: не удалось подключиться к S3 при старте: {exc}")


@app.get("/health", tags=["system"])
def health_check():
    """Эндпоинт проверки работоспособности сервиса."""
    return {"status": "ok", "service": "hub-backend-mvp"}

@app.on_event("startup")
def startup_event():
    init_db()
    s3 = get_s3_client()
    try:
        s3.ensure_bucket()
        print("✅ Успешное подключение к S3 и инициализация БД выполнены.")
    except Exception as exc:
        print(f"⚠️ Ошибка при старте: {exc}")