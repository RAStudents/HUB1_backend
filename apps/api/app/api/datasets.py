import tempfile
import zipfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from apps.api.app.deps import CurrentUser, get_current_user, get_dataset_service
from core.application.dataset_service import DatasetService
from core.application.visualizer import build_dataset_gallery, STORAGE_DIR
from core.domain.enums import TaskTypeEnum
from core.infrastructure.media.scratch import scratch_file

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_dataset(
    payload: dict,
    user: CurrentUser = Depends(get_current_user),
    service: DatasetService = Depends(get_dataset_service),
):
    """Создание нового датасета."""
    task_str = payload.get("task", "detect")
    task_enum = TaskTypeEnum(task_str) if isinstance(task_str, str) else task_str

    dataset_id = service.create_dataset(
        name=payload.get("name", "Unnamed Dataset"),
        task=task_enum,
        owner_id=user.id,
        description=payload.get("description"),
        is_private=payload.get("is_private", True),
        initial_classes=payload.get("classes"),
    )
    return {"dataset_id": dataset_id, "message": "Датасет успешно создан"}


@router.get("/{dataset_id}/gallery")
def get_dataset_gallery(
    dataset_id: int,
    request: Request,
    yaml_path: Optional[str] = Query(None, description="Путь к data.yaml или папке датасета на диске"),
    split: str = Query("train"),
    limit: int = Query(50, ge=1, le=500),
):
    """Получение галереи с оверлеями по локальному пути или из уже распакованного хранилища."""
    base_url = str(request.base_url).rstrip("/")

    # Если путь не передан явно, ищем в стандартных папках проекта
    target_path = Path(yaml_path) if yaml_path else (STORAGE_DIR / f"dataset_{dataset_id}")

    try:
        items = build_dataset_gallery(
            dataset_id=dataset_id,
            yaml_path=target_path,
            split_name=split,
            limit=limit,
            base_url=base_url,
        )
        return items
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/{dataset_id}/gallery-file")
async def get_dataset_gallery_by_file(
    dataset_id: int,
    request: Request,
    file: UploadFile = File(...),
    split: str = "train",
    limit: int = 50,
    dataset_dir: Optional[str] = Form(None, description="Опциональный путь к папке датасета, если загружается только yaml"),
):
    """Загрузка .zip архива датасета или .yaml файла для генерации локального preview с overlay."""
    base_url = str(request.base_url).rstrip("/")
    filename = file.filename or "data.yaml"
    suffix = Path(filename).suffix.lower()
    content = await file.read()

    try:
        # 1. Если загрузили ZIP-архив целиком — распаковываем в постоянную папку датасета и строим галерею
        if suffix == ".zip":
            extract_dir = STORAGE_DIR / f"dataset_{dataset_id}" / "raw"
            extract_dir.mkdir(parents=True, exist_ok=True)
            with scratch_file(suffix=".zip", data=content) as tmp_zip:
                with zipfile.ZipFile(tmp_zip, "r") as zf:
                    zf.extractall(extract_dir)

            return build_dataset_gallery(
                dataset_id=dataset_id,
                yaml_path=extract_dir,
                split_name=split,
                limit=limit,
                base_url=base_url,
            )

        # 2. Если вместе с YAML передали путь к локальной папке датасета
        if dataset_dir:
            target_dir = Path(dataset_dir)
            if not target_dir.exists():
                raise ValueError(f"Папка не найдена: {dataset_dir}")
            tmp_yaml = target_dir / "data.yaml"
            if not tmp_yaml.exists():
                tmp_yaml.write_bytes(content)
            return build_dataset_gallery(
                dataset_id=dataset_id,
                yaml_path=tmp_yaml,
                split_name=split,
                limit=limit,
                base_url=base_url,
            )

        # 3. Если загружен только .yaml файл — сохраняем во временный файл
        with scratch_file(suffix=suffix or ".yaml", data=content) as tmp_yaml:
            return build_dataset_gallery(
                dataset_id=dataset_id,
                yaml_path=tmp_yaml,
                split_name=split,
                limit=limit,
                base_url=base_url,
            )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))