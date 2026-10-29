# apps/api/app/api/router.py
from fastapi import APIRouter

from apps.api.app.api import auth, datasets, samples, annotations, export

api_router = APIRouter(prefix="/api")

# Подключаем модульные роутеры MVP
api_router.include_router(auth.router)
api_router.include_router(datasets.router)
api_router.include_router(samples.router)
api_router.include_router(annotations.router)
api_router.include_router(export.router)