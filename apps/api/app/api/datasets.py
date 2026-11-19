# apps/api/app/api/datasets.py

import shutil
import logging
from pathlib import Path
from typing import Optional
from collections import Counter
from acmenra_cv import TaskType

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile, status

from apps.api.app.deps import (
    DatasetId,
    CurrentUser,
    get_current_user,
    get_class_repo,
    get_dataset_or_404,
    get_dataset_repo,
    get_dataset_service,
    get_dataset_statistics_service,
    get_import_job_repo,
    get_sample_repo,
    get_s3_client,
    require_dataset_role,
)
from apps.api.app.errors import client_error
from apps.api.app.uploads import spool_upload
from apps.api.app.schemas.import_job import ImportJobDTO
from apps.api.app.import_tasks import run_new_dataset_import
from apps.api.app.schemas.dataset import CreateDatasetRequest
from apps.api.app.schemas.dataset_statistics import DatasetStatisticsDTO

from core.application.dataset_service import DatasetService
from core.application.dataset_statistics_service import DatasetStatisticsService
from core.infrastructure.s3.client import S3Client
from core.infrastructure.s3.keys import clean_filename, clean_split


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/datasets", tags=["datasets"])


STORAGE_DIR = Path("storage")


def _gallery_item(row, class_names,
                  s3: S3Client,
                  base_url: str,
                  sample_repo) -> dict:
    annotations = sample_repo.get_geometries(getattr(row, "geometry_json", None))
    counts = Counter(
        item["class_id"]
        for item in annotations
        if isinstance(item, dict) and isinstance(item.get("class_id"), int)
    )
    filename = Path(row.image_key).name
    return {
        "id": row.id,
        "sample_id": row.id,
        "filename": filename,
        "split": row.split,
        "status": row.status,
        "is_labeled": row.is_labeled,
        "image_url": s3.get_presigned_url(row.image_key, base_url=base_url),
        "mask_url": s3.get_presigned_url(row.thumb_key, base_url=base_url) if row.thumb_key else None,
        "objects_count": len(annotations),
        "visible_objects_count": len(annotations),
        "annotation_classes": [
            {
                "id": class_id,
                "name": class_names[class_id] if 0 <= class_id < len(class_names) else f"Класс {class_id}",
                "count": count,
            }
            for class_id, count in sorted(counts.items())
        ],
    }


@router.get("/")
def list_my_datasets(request: Request,
                     user: CurrentUser = Depends(get_current_user),
                     service: DatasetService = Depends(get_dataset_service)):
    base_url = str(request.base_url).rstrip("/")
    items = service.list_user_datasets(user_id=user.id, base_url=base_url)
    return {"total": len(items), "items": items}


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_dataset(payload: CreateDatasetRequest,
                   user: CurrentUser = Depends(get_current_user),
                   service: DatasetService = Depends(get_dataset_service)):
    dataset_id = service.create_dataset(
        name=payload.name,
        task=TaskType(payload.task),
        owner_id=user.id,
        description=payload.description,
        is_private=payload.is_private,
        initial_classes=payload.classes,
    )
    return {"dataset_id": service.datasets.get_by_id(dataset_id).public_id, "message": "Датасет успешно создан в БД"}


@router.get("/{dataset_id}/statistics", response_model=DatasetStatisticsDTO)
def get_dataset_statistics(dataset_id: DatasetId,
                           grid_size: int = Query(20, ge=1, le=100),
                           _user: CurrentUser = Depends(
                               require_dataset_role({"owner", "labeler", "observer"})
                           ),
                           dataset=Depends(get_dataset_or_404),
                           service: DatasetStatisticsService = Depends(
                               get_dataset_statistics_service
                           )) -> DatasetStatisticsDTO:
    result = service.get_statistics(
        dataset_id=dataset_id,
        task=TaskType(dataset.task),
        grid_size=grid_size,
    )

    return {**result, "dataset_id": dataset.public_id}


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dataset(dataset_id: DatasetId,
                   user: CurrentUser = Depends(require_dataset_role({"owner"})),
                   dataset=Depends(get_dataset_or_404),
                   service: DatasetService = Depends(get_dataset_service),
                   s3: S3Client = Depends(get_s3_client)) -> None:
    """Удаляет датасет владельца, его файлы и связанные записи."""
    s3.delete_prefix(f"datasets/{dataset_id}/")

    legacy_storage = STORAGE_DIR / f"dataset_{dataset_id}"
    if legacy_storage.exists():
        shutil.rmtree(legacy_storage)

    service.delete_dataset(dataset_id=dataset_id)


@router.delete("/{dataset_id}/gallery-item", status_code=status.HTTP_204_NO_CONTENT)
def delete_gallery_item(dataset_id: DatasetId,
                        filename: str = Query(...),
                        split: str = Query("train"),
                        user: CurrentUser = Depends(require_dataset_role({"owner"})),
                        dataset=Depends(get_dataset_or_404),
                        s3: S3Client = Depends(get_s3_client),
                        sample_repo=Depends(get_sample_repo)) -> None:
    """Удаляет картинку из БД и S3, плюс старый файл кэша по фиксированному пути."""
    try:
        safe_name = clean_filename(filename)
        split_name = clean_split(split)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=client_error(exc)) from exc

    stem = Path(safe_name).stem
    rows = sample_repo.list_by_stem(dataset_id=dataset_id, split=split_name, stem=stem)
    if not rows and split.lower() == "valid":
        rows = sample_repo.list_by_stem(dataset_id=dataset_id, split="valid", stem=stem)
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Изображение не найдено")

    for sample in rows:
        s3.delete_many([sample.image_key, sample.label_key, sample.thumb_key])
        sample_repo.delete(sample_id=sample.id)

    legacy = STORAGE_DIR / f"dataset_{dataset_id}" / split_name
    (legacy / "images" / safe_name).unlink(missing_ok=True)
    (legacy / "masks" / f"{stem}_mask.png").unlink(missing_ok=True)


@router.post("/upload", response_model=ImportJobDTO, status_code=status.HTTP_202_ACCEPTED)
async def upload_and_save_dataset(request: Request,
                            background_tasks: BackgroundTasks,
                            name: str = Form(...),
                            task: str = Form(...),
                            is_private: bool = Form(True),
                            file: UploadFile = File(...),
                            user: CurrentUser = Depends(get_current_user),
                            import_job_repo=Depends(get_import_job_repo),
                            dataset_repo=Depends(get_dataset_repo)) -> ImportJobDTO:
    if not file.filename or Path(file.filename).suffix.lower() != ".zip":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Загрузите ZIP-архив со всем датасетом",
        )

    try:
        selected_task = TaskType(task)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Неизвестный тип задачи: {task}",
        ) from exc

    content_path = await spool_upload(file)
    try:
        import_record = import_job_repo.create(user_id=user.id)
        background_tasks.add_task(
            run_new_dataset_import,
            import_id=import_record.id,
            zip_path=str(content_path),
            user_id=user.id,
            name=name,
            task=selected_task.value,
            is_private=is_private,
            base_url=str(request.base_url).rstrip("/"),
        )
    except Exception:
        Path(content_path).unlink(missing_ok=True)
        raise

    return ImportJobDTO(
        import_id=import_record.id,
        dataset_id=dataset_repo.get_by_id(import_record.dataset_id).public_id if import_record.dataset_id is not None else None,
        status=import_record.status,
        stage=import_record.stage,
        progress=import_record.progress,
        total_samples=import_record.total_samples,
        processed_samples=import_record.processed_samples,
        imported_samples=import_record.imported_samples,
        parse_errors=import_record.parse_errors,
        error=import_record.error,
        created_at=import_record.created_at,
    )


@router.get("/imports/{import_id}", response_model=ImportJobDTO)
def get_import_status(import_id: int,
                      user: CurrentUser = Depends(get_current_user),
                      import_job_repo=Depends(get_import_job_repo),
                            dataset_repo=Depends(get_dataset_repo)) -> ImportJobDTO:
    record = import_job_repo.get_by_id(import_id)
    if record is None or record.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Задание импорта не найдено",
        )
    return ImportJobDTO(
        import_id=record.id,
        dataset_id=dataset_repo.get_by_id(record.dataset_id).public_id if record.dataset_id is not None else None,
        status=record.status,
        stage=record.stage,
        progress=record.progress,
        total_samples=record.total_samples,
        processed_samples=record.processed_samples,
        imported_samples=record.imported_samples,
        parse_errors=record.parse_errors,
        error=record.error,
        created_at=record.created_at,
    )


@router.get("/{dataset_id}/gallery")
def get_dataset_gallery(dataset_id: DatasetId,
                        request: Request,
                        response: Response,
                        split: str = Query("train"),
                        limit: int = Query(50, ge=1, le=500),
                        offset: int = Query(0, ge=0),
                        class_ids: list[int] | None = Query(None),
                        filenames: list[str] | None = Query(None),
                        _user: CurrentUser = Depends(
                            require_dataset_role({"owner", "labeler", "observer"})
                        ),
                        dataset=Depends(get_dataset_or_404),
                        sample_repo=Depends(get_sample_repo),
                        class_repo=Depends(get_class_repo),
                        s3: S3Client = Depends(get_s3_client)):
    normalized = (split or "train").lower()
    try:
        split_arg = None if normalized == "all" else clean_split(normalized)
        stems = [Path(clean_filename(name)).stem for name in filenames] if filenames else None
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=client_error(exc)) from exc

    total, rows = sample_repo.paginate_gallery(
        dataset_id=dataset_id,
        split=split_arg,
        status=None,
        labeled=None,
        search=None,
        object_count=None,
        class_ids=class_ids or [],
        offset=offset,
        limit=limit,
        stems=stems,
    )
    class_names = class_repo.get_names(dataset_id)
    base_url = str(request.base_url).rstrip("/")
    response.headers["X-Total-Count"] = str(total)
    return [
        _gallery_item(row, class_names, s3, base_url, sample_repo)
        for row in rows
    ]