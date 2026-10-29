# apps/api/app/api/export.py
from fastapi import APIRouter, Depends, HTTPException, Query, status

from acmenra_cv import TaskType
from acmenra_ds import DatasetLayout
from apps.api.app.deps import (
    CurrentUser,
    get_current_user,
    get_dataset_or_404,
    get_export_repo,
    get_export_service,
    get_s3_client,
)
from apps.api.app.schemas.export import ExportStatusDTO
from core.application.export_service import ExportService
from core.infrastructure.s3.client import S3Client
from apps.api.app.deps import require_dataset_role

router = APIRouter(prefix="/datasets/{dataset_id}/exports", tags=["export"])


@router.post("", response_model=ExportStatusDTO, status_code=status.HTTP_201_CREATED)
def start_export(
    dataset_id: int,
    layout: str = Query("direct", description="direct (train/images) | reverse (images/train)"),
    user: CurrentUser = Depends(require_dataset_role({"owner"})), # <--- Ограничили только владельцем
    dataset=Depends(get_dataset_or_404),
    service: ExportService = Depends(get_export_service),
) -> ExportStatusDTO:
    """Запускает сборку ZIP-архива из accepted-кадров и возвращает статус + ссылку."""
    ds_layout = (
        DatasetLayout.REVERSE if layout.lower() == "reverse" else DatasetLayout.DIRECT
    )
    try:
        result = service.build_export_zip(
            dataset_id=dataset_id,
            user_id=user.id,
            task=TaskType(dataset.task),
            layout=ds_layout,
        )
        return ExportStatusDTO(**result)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get("/{export_id}", response_model=ExportStatusDTO)
def get_export_status(
    dataset_id: int,
    export_id: int,
    user: CurrentUser = Depends(get_current_user),
    dataset=Depends(get_dataset_or_404),
    export_repo=Depends(get_export_repo),
    s3: S3Client = Depends(get_s3_client),
) -> ExportStatusDTO:
    """Проверяет статус сборки архива и выдаёт свежую presigned-ссылку на скачивание."""
    record = export_repo.get_by_id(dataset_id=dataset_id, export_id=export_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Экспорт не найден")

    download_url = (
        s3.get_presigned_url(record.s3_key)
        if record.status == "completed" and record.s3_key
        else None
    )
    return ExportStatusDTO(
        export_id=record.id,
        status=record.status,
        exported_samples=getattr(record, "exported_samples", 0),
        download_url=download_url,
        error=getattr(record, "error", None),
    )

