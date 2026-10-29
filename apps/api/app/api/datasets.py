import zipfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status

from apps.api.app.deps import CurrentUser, get_current_user, get_dataset_service
from core.application.dataset_service import DatasetService
from core.application.visualizer import STORAGE_DIR, build_dataset_gallery
from core.domain.enums import TaskTypeEnum
from core.infrastructure.media.scratch import scratch_file

router = APIRouter(prefix="/datasets", tags=["datasets"])

# ... (ваши остальные роутеры create_dataset и т.д.)


@router.get("/{dataset_id}/gallery")
def get_dataset_gallery(
    dataset_id: int,
    request: Request,
    yaml_path: Optional[str] = Query(None, description="Путь к data.yaml или папке датасета на диске"),
    split: str = Query("train", description="Сплит: train, val, test"),
    limit: int = Query(50, ge=1, le=500, description="Лимит кадров"),
):
    """
    Получение галереи кадров с оверлеями (масками/боксами) по локальному пути
    или из уже распакованного хранилища датасета.
    """
    base_url = str(request.base_url).rstrip("/")
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
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/{dataset_id}/gallery-file")
async def get_dataset_gallery_by_file(
    dataset_id: int,
    request: Request,
    file: UploadFile = File(...),
    split: str = Form("train", description="Сплит: train, val, test"),
    limit: int = Form(50, description="Лимит кадров"),
    dataset_dir: Optional[str] = Form(
        None, description="Путь к локальной папке датасета, если загружается только yaml"
    ),
):
    """
    Загрузка .zip архива датасета или .yaml файла для генерации превью с overlay.
    Поддерживает три сценария:
    1. Загрузка ZIP — распаковывает в постоянное хранилище и строит галерею.
    2. Загрузка YAML + указание dataset_dir — берет разметку и связывает с локальной папкой.
    3. Загрузка чистого YAML — обрабатывает во временном файле.
    """
    base_url = str(request.base_url).rstrip("/")
    filename = file.filename or "data.yaml"
    suffix = Path(filename).suffix.lower()
    content = await file.read()

    try:
        # Сценарий 1: ZIP-архив целиком
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

        # Сценарий 2: YAML + путь к локальной папке
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

        # Сценарий 3: Одиночный .yaml файл
        with scratch_file(suffix=suffix or ".yaml", data=content) as tmp_yaml:
            return build_dataset_gallery(
                dataset_id=dataset_id,
                yaml_path=tmp_yaml,
                split_name=split,
                limit=limit,
                base_url=base_url,
            )

    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))