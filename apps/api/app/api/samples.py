# apps/api/app/api/samples.py
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from acmenra_cv import TaskType

from apps.api.app.deps import (
    CurrentUser,
    get_current_user,
    get_dataset_or_404,
    get_import_service,
    get_s3_client,
    get_sample_repo,
    require_dataset_role,
)
from apps.api.app.schemas.sample import (
    CompleteUploadRequest,
    GalleryPageDTO,
    SampleCardDTO,
    UploadUrlRequest,
    UploadUrlResponse,
)
from core.application.import_service import ImportService
from core.infrastructure.cv.thumbs import render_thumbnail_bytes
from core.infrastructure.media.convert import normalize_image_file
from core.infrastructure.media.scratch import scratch_file
from core.infrastructure.s3.client import S3Client
from core.infrastructure.s3.keys import image_key, label_key, thumb_key

router = APIRouter(prefix="/datasets/{dataset_id}/samples", tags=["samples"])


@router.get("", response_model=GalleryPageDTO)
def list_gallery_samples(
    dataset_id: int,
    split: Optional[str] = Query(None, description="train | val | test | None (все)"),
    sample_status: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(24, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
    dataset=Depends(get_dataset_or_404),
    s3: S3Client = Depends(get_s3_client),
    sample_repo=Depends(get_sample_repo),
) -> GalleryPageDTO:
    """
    Галерея кадров с фильтрацией по сплиту и статусу.
    Генерирует presigned URL на оригинал и превью (тумбу с масками) для каждой карточки.
    """
    normalized_split = split.lower() if split and split.lower() != "all" else None

    total, rows = sample_repo.paginate(
        dataset_id=dataset_id,
        split=normalized_split,
        status=sample_status,
        offset=(page - 1) * page_size,
        limit=page_size,
    )

    items = [
        SampleCardDTO(
            id=row.id,
            dataset_id=dataset_id,
            stem=row.stem,
            split=row.split,
            status=row.status,
            is_labeled=row.is_labeled,
            image_url=s3.get_presigned_url(row.image_key),
            thumb_url=s3.get_presigned_url(row.thumb_key),
            lock_user=row.lock_user,
            lock_until=row.lock_until,
            parse_error=row.parse_error,
        )
        for row in rows
    ]
    return GalleryPageDTO(total=total, page=page, page_size=page_size, items=items)


@router.post("/import-zip")
async def import_dataset_zip(
    dataset_id: int,
    file: UploadFile = File(...),
    user: CurrentUser = Depends(require_dataset_role({"owner", "labeler"})),
    dataset=Depends(get_dataset_or_404),
    import_service: ImportService = Depends(get_import_service),
) -> dict:
    """Принимает ZIP с датасетом, проходит по train/val/test и строит все превью с масками."""
    zip_bytes = await file.read()
    try:
        return import_service.import_zip(
            dataset_id=dataset_id,
            task=TaskType(dataset.task),
            zip_source=zip_bytes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/upload-url", response_model=UploadUrlResponse)
def get_upload_url(
    dataset_id: int,
    req: UploadUrlRequest,
    user: CurrentUser = Depends(require_dataset_role({"owner", "labeler"})),
    s3: S3Client = Depends(get_s3_client),
) -> UploadUrlResponse:
    """Выдаёт presigned PUT ссылку для прямой загрузки кадра во временный префикс S3."""
    raw_key = f"datasets/{dataset_id}/_incoming/{req.split.lower()}/{req.filename}"
    url = s3.get_presigned_upload_url(key=raw_key, content_type=req.content_type)
    return UploadUrlResponse(upload_key=raw_key, upload_url=url)


@router.post("/complete-upload", response_model=SampleCardDTO)
def complete_upload(
    dataset_id: int,
    req: CompleteUploadRequest,
    user: CurrentUser = Depends(require_dataset_role({"owner", "labeler"})),
    dataset=Depends(get_dataset_or_404),
    s3: S3Client = Depends(get_s3_client),
    sample_repo=Depends(get_sample_repo),
) -> SampleCardDTO:
    """
    Завершает загрузку одиночного кадра:
    конвертирует (heic/webp → jpg), создаёт пустой .txt и превью, регистрирует сэмпл в БД.
    """
    raw_bytes = s3.get_bytes(req.upload_key)
    if not raw_bytes:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Загруженный файл не найден в S3")

    orig_name = Path(req.upload_key).name
    split_name = req.split.lower()

    with scratch_file(suffix=Path(orig_name).suffix, data=raw_bytes) as tmp_src:
        img_bytes, norm_filename, content_type = normalize_image_file(tmp_src)
        stem = Path(norm_filename).stem

        with scratch_file(suffix=Path(norm_filename).suffix, data=img_bytes) as tmp_norm:
            thumb_bytes = render_thumbnail_bytes(
                image_path=tmp_norm,
                instances=[],
                task=TaskType(dataset.task),
            )

    s3_img_key = image_key(dataset_id, split_name, norm_filename)
    s3_lbl_key = label_key(dataset_id, split_name, stem)
    s3_thb_key = thumb_key(dataset_id, split_name, stem)

    s3.put_bytes(s3_img_key, img_bytes, content_type=content_type)
    s3.put_bytes(s3_lbl_key, b"", content_type="text/plain")
    s3.put_bytes(s3_thb_key, thumb_bytes, content_type="image/jpeg")
    s3.delete(req.upload_key)

    row = sample_repo.create_sample(
        dataset_id=dataset_id,
        stem=stem,
        split=split_name,
        image_key=s3_img_key,
        label_key=s3_lbl_key,
        thumb_key=s3_thb_key,
        is_labeled=False,
        parse_error=None,
    )

    return SampleCardDTO(
        id=row.id,
        dataset_id=dataset_id,
        stem=row.stem,
        split=row.split,
        status=row.status,
        is_labeled=row.is_labeled,
        image_url=s3.get_presigned_url(s3_img_key),
        thumb_url=s3.get_presigned_url(s3_thb_key),
    )


@router.delete("/{sample_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sample(
    dataset_id: int,
    sample_id: int,
    user: CurrentUser = Depends(require_dataset_role({"owner"})),
    s3: S3Client = Depends(get_s3_client),
    sample_repo=Depends(get_sample_repo),
) -> None:
    """Удаляет сэмпл из БД и чистит его файлы (оригинал, .txt, превью) из S3."""
    row = sample_repo.get_by_id(dataset_id=dataset_id, sample_id=sample_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Кадр не найден")

    s3.delete_many([row.image_key, row.label_key, row.thumb_key])
    sample_repo.delete(sample_id=sample_id)
