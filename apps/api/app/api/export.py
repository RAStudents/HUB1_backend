# apps/api/app/api/export.py

import logging
from io import BytesIO
from urllib.parse import quote
from acmenra_cv import TaskType

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from apps.api.app.deps import (
    CurrentUser,
    get_dataset_or_404,
    get_export_repo,
    get_export_service,
    get_s3_client,
)
from apps.api.app.schemas.export import ExportStatusDTO
from core.application.export_service import ExportService
from core.infrastructure.s3.client import S3Client
from apps.api.app.deps import require_dataset_role


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/datasets/{dataset_id}/exports",
                   tags=["export"])


@router.post("", response_model=ExportStatusDTO, status_code=status.HTTP_201_CREATED)
def start_export(dataset_id: int,
                 request: Request,
                 user: CurrentUser = Depends(require_dataset_role({"owner"})),
                 dataset=Depends(get_dataset_or_404),
                 service: ExportService = Depends(get_export_service)) -> ExportStatusDTO:
    """Создаёт ZIP с принятыми кадрами в прямой раскладке YOLO."""
    try:
        result = service.build_export_zip(
            dataset_id=dataset_id,
            user_id=user.id,
            task=TaskType(dataset.task),
        )
        result["download_url"] = (
            f"{str(request.base_url).rstrip('/')}"
            f"/api/datasets/{dataset_id}/exports/{result['export_id']}/download"
        )
        return ExportStatusDTO(**result)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.get(
    "/{export_id}",
    response_model=ExportStatusDTO,
    dependencies=[
        Depends(require_dataset_role({"owner"})),
        Depends(get_dataset_or_404),
    ],
)
def get_export_status(dataset_id: int,
                      export_id: int,
                      request: Request,
                      export_repo=Depends(get_export_repo)) -> ExportStatusDTO:
    """Проверяет статус сборки архива и возвращает ссылку на его скачивание."""
    record = export_repo.get_by_id(dataset_id=dataset_id, export_id=export_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Экспорт не найден")

    download_url = (
        f"{str(request.base_url).rstrip('/')}"
        f"/api/datasets/{dataset_id}/exports/{export_id}/download"
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


@router.get(
    "/{export_id}/download",
    dependencies=[
        Depends(require_dataset_role({"owner"})),
        Depends(get_dataset_or_404),
    ],
)
def download_export(dataset_id: int,
                    export_id: int,
                    dataset=Depends(get_dataset_or_404),
                    export_repo=Depends(get_export_repo),
                    s3: S3Client = Depends(get_s3_client)):
    record = export_repo.get_by_id(dataset_id=dataset_id, export_id=export_id)
    if record is None or record.status != "completed" or not record.s3_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Архив экспорта не найден")

    zip_bytes = s3.get_bytes(record.s3_key)
    if zip_bytes is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Архив экспорта не найден в хранилище")

    filename = dataset.name.strip().replace("/", "_").replace("\\", "_") or f"dataset_{dataset_id}"
    encoded_filename = quote(f"{filename}.zip", safe="")
    return StreamingResponse(
        BytesIO(zip_bytes),
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="dataset_{dataset_id}.zip"; '
                f"filename*=UTF-8''{encoded_filename}"
            )
        },
    )
