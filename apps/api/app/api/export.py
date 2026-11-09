# apps/api/app/api/export.py

import logging
from io import BytesIO
from urllib.parse import quote
from acmenra_cv import TaskType

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
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


@router.post("", response_model=ExportStatusDTO, status_code=status.HTTP_202_ACCEPTED)
def start_export(dataset_id: int,
                 background_tasks: BackgroundTasks,
                 user: CurrentUser = Depends(require_dataset_role({"owner"})),
                 dataset=Depends(get_dataset_or_404),
                 export_repo=Depends(get_export_repo),
                 service: ExportService = Depends(get_export_service)) -> ExportStatusDTO:
    """Создаёт ZIP с принятыми кадрами в прямой раскладке YOLO."""
    accepted_samples = service.samples.list_by_status(
        dataset_id=dataset_id, status="accepted"
    )
    export_record = export_repo.create_export(
        dataset_id=dataset_id,
        user_id=user.id,
        total_samples=len(accepted_samples),
    )
    background_tasks.add_task(
        service.build_export_zip,
        dataset_id=dataset_id,
        user_id=user.id,
        task=TaskType(dataset.task),
        export_id=export_record.id,
        accepted_samples=accepted_samples,
    )
    return ExportStatusDTO(
        export_id=export_record.id,
        status="processing",
        total_samples=len(accepted_samples),
    )


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

    export_stage = getattr(record, "stage", record.status)
    download_url = (
        f"{str(request.base_url).rstrip('/')}"
        f"/api/datasets/{dataset_id}/exports/{export_id}/download"
        if record.status == "completed" and record.s3_key
        else None
    )
    return ExportStatusDTO(
        export_id=record.id,
        status=record.status,
        stage=export_stage,
        exported_samples=getattr(record, "exported_samples", 0),
        total_samples=getattr(record, "total_samples", 0),
        progress=(
            100
            if record.status == "completed"
            else min(75, int(record.exported_samples * 75 / record.total_samples))
            if record.total_samples and export_stage == "processing"
            else {
                "validating": 80,
                "packaging": 85,
                "uploading": 90,
                "finalizing": 98,
            }.get(export_stage, 0)
        ),
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
            ),
            "Content-Length": str(len(zip_bytes)),
        },
    )
