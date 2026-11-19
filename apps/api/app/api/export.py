# apps/api/app/api/export.py

import logging
from io import BytesIO
from urllib.parse import quote
from acmenra_cv import TaskType

from fastapi.responses import FileResponse, RedirectResponse
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status

from apps.api.app.deps import (
    DatasetId,
    CurrentUser,
    get_class_repo,
    get_dataset_or_404,
    get_export_repo,
    get_export_service,
    get_sample_repo,
    get_s3_client,
)

from apps.api.app.schemas.export import ExportClassDTO, ExportRequestDTO, ExportStatusDTO
from core.application.export_service import ExportService
from core.infrastructure.s3.client import S3Client
from apps.api.app.deps import require_dataset_role


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/datasets/{dataset_id}/exports",
                   tags=["export"])


def _normalize_split(split: str | None) -> str:
    normalized = (split or "train").lower()
    return "val" if normalized == "valid" else normalized


@router.post("", response_model=ExportStatusDTO, status_code=status.HTTP_202_ACCEPTED)
def start_export(dataset_id: DatasetId,
                 background_tasks: BackgroundTasks,
                 payload: ExportRequestDTO | None = None,
                 user: CurrentUser = Depends(require_dataset_role({"owner"})),
                 dataset=Depends(get_dataset_or_404),
                 export_repo=Depends(get_export_repo),
                 service: ExportService = Depends(get_export_service)) -> ExportStatusDTO:
    """Создаёт ZIP с принятыми кадрами в прямой раскладке YOLO."""
    selected_splits = payload.splits if payload is not None else None
    if selected_splits is not None:
        if not selected_splits:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Выберите хотя бы один сплит для экспорта",
            )
        selected_splits = sorted(set(selected_splits))

    class_names = service.classes.get_names(dataset_id=dataset_id)
    class_ids = payload.class_ids if payload is not None else None
    if class_ids is not None:
        if not class_ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Выберите хотя бы один класс для экспорта",
            )
        invalid_class_ids = sorted(set(class_ids) - set(range(len(class_names))))
        if invalid_class_ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Неизвестные ID классов: {invalid_class_ids}",
            )
        class_ids = sorted(set(class_ids))

    if class_ids is not None:
        accepted_samples = service.samples.list_by_status_and_class_ids(
            dataset_id=dataset_id,
            status="accepted",
            class_ids=class_ids,
        )
    else:
        accepted_samples = service.samples.list_by_status(
            dataset_id=dataset_id, status="accepted"
        )

    if selected_splits is not None:
        accepted_samples = [
            sample
            for sample in accepted_samples
            if _normalize_split(sample.split) in selected_splits
        ]

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
        selected_class_ids=class_ids,
        selected_splits=selected_splits,
    )
    return ExportStatusDTO(
        export_id=export_record.id,
        status="processing",
        total_samples=len(accepted_samples),
    )


@router.get(
    "/classes",
    response_model=list[ExportClassDTO],
    dependencies=[
        Depends(require_dataset_role({"owner"})),
        Depends(get_dataset_or_404),
    ],
)
def list_export_classes(dataset_id: DatasetId,
                        class_repo=Depends(get_class_repo),
                        sample_repo=Depends(get_sample_repo)) -> list[ExportClassDTO]:
    classes = class_repo.list_for_dataset(dataset_id)
    class_counts = sample_repo.get_class_counts(dataset_id)
    return [
        ExportClassDTO(
            id=class_row.class_index,
            name=class_row.name,
            count=class_counts.get(class_row.class_index, 0),
        )
        for class_row in classes
    ]


@router.get(
    "/{export_id}",
    response_model=ExportStatusDTO,
    dependencies=[
        Depends(require_dataset_role({"owner"})),
        Depends(get_dataset_or_404),
    ],
)
def get_export_status(dataset_id: DatasetId,
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
        f"/api/datasets/{request.path_params['dataset_id']}/exports/{export_id}/download"
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
def download_export(dataset_id: DatasetId,
                    export_id: int,
                    dataset=Depends(get_dataset_or_404),
                    export_repo=Depends(get_export_repo),
                    s3: S3Client = Depends(get_s3_client)):
    record = export_repo.get_by_id(dataset_id=dataset_id, export_id=export_id)
    if record is None or record.status != "completed" or not record.s3_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Архив экспорта не найден")

    if not str(record.s3_key).startswith(f"datasets/{int(dataset_id)}/exports/"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Архив экспорта не найден")
    if s3.is_remote:
        try:
            url = s3.get_presigned_url(record.s3_key, expires_in=300)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Архив экспорта не найден") from exc
        return RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    try:
        zip_path = s3.safe_path(record.s3_key)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Архив экспорта не найден") from exc
    if not zip_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Архив экспорта не найден в хранилище")

    filename = dataset.name.strip().replace("/", "_").replace("\\", "_") or f"dataset_{dataset_id}"
    encoded_filename = quote(f"{filename}.zip", safe="")
    return FileResponse(
        zip_path,
        media_type="application/zip",
        headers={
            "Content-Disposition": (
                f'attachment; filename="dataset_{dataset_id}.zip"; '
                f"filename*=UTF-8''{encoded_filename}"
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )
