# apps/api/app/api/samples.py

import logging
from pathlib import Path
from typing import Optional
from acmenra_cv import TaskType
from collections import Counter

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, Request, UploadFile, status

from apps.api.app.deps import (
    CurrentUser,
    get_current_user,
    get_annotation_repo,
    get_class_repo,
    get_dataset_or_404,
    get_import_job_repo,
    get_s3_client,
    get_sample_repo,
    require_dataset_role,
)
from apps.api.app.schemas.sample import (
    GalleryClassDTO,
    CompleteUploadRequest,
    GalleryPageDTO,
    SampleCardDTO,
    UploadUrlRequest,
    UploadUrlResponse,
)
from apps.api.app.schemas.import_job import ImportJobDTO
from apps.api.app.import_tasks import run_existing_dataset_import
from apps.api.app.uploads import spool_upload
from apps.api.app.errors import client_error
from core.infrastructure.s3.client import S3Client
from core.infrastructure.cv.labels import parse_label_file
from core.infrastructure.cv.mapper import instances_to_dtos
from core.infrastructure.media.scratch import scratch_file
from core.infrastructure.cv.thumbs import render_thumbnail_bytes
from core.infrastructure.media.convert import normalize_image_file
from core.infrastructure.s3.keys import clean_filename, clean_split, image_key, incoming_key, label_key, thumb_key


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/datasets/{dataset_id}/samples", tags=["samples"])


@router.get("", response_model=GalleryPageDTO)
def list_gallery_samples(request: Request,
                         dataset_id: int,
                         split: Optional[str] = Query(None, description="train | val | test | None (все)"),
                         sample_status: Optional[str] = Query(None, alias="status"),
                         search: Optional[str] = Query(None, max_length=255),
                         labeled: Optional[bool] = Query(None),
                         object_count: Optional[str] = Query(None, pattern="^(none|one|multiple)$"),
                         class_ids: list[int] | None = Query(None),
                         page: int = Query(1, ge=1),
                         page_size: int = Query(24, ge=1, le=100),
                         user: CurrentUser = Depends(
                             require_dataset_role({"owner", "labeler", "observer"})
                         ),
                         dataset=Depends(get_dataset_or_404),
                         s3: S3Client = Depends(get_s3_client),
                         sample_repo=Depends(get_sample_repo),
                         annotation_repo=Depends(get_annotation_repo),
                         class_repo=Depends(get_class_repo)) -> GalleryPageDTO:
    """Возвращает только одну страницу карточек и геометрию разметки."""
    normalized_split = split.lower() if split and split.lower() != "all" else None
    class_names = class_repo.get_names(dataset_id)
    task = TaskType(dataset.task)

    total, rows = sample_repo.paginate_gallery(
        dataset_id=dataset_id,
        split=normalized_split,
        status=sample_status,
        labeled=labeled,
        search=search.strip() if search else None,
        object_count=object_count,
        class_ids=class_ids or [],
        offset=(page - 1) * page_size,
        limit=page_size,
    )

    items = []
    for row in rows:
        annotations = sample_repo.get_geometries(row.geometry_json)
        if not row.geometry_json:
            raw_label = s3.get_bytes(row.label_key)
            if raw_label:
                with scratch_file(suffix=".txt", data=raw_label) as label_path:
                    instances = parse_label_file(
                        path=label_path,
                        class_names=class_names,
                        task=task,
                    )
                annotations = [
                    item.model_dump(mode="json")
                    for item in instances_to_dtos(instances, task)
                ]

        per_class_counts = Counter(
            item["class_id"] for item in annotations
        )
        class_catalog = [
            GalleryClassDTO(
                id=class_id,
                name=class_names[class_id] if 0 <= class_id < len(class_names) else f"Класс {class_id}",
                count=count,
            )
            for class_id, count in sorted(per_class_counts.items())
        ]
        items.append(SampleCardDTO(
            id=row.id,
            sample_id=row.id,
            dataset_id=dataset_id,
            stem=row.stem,
            split=row.split,
            status=row.status,
            is_labeled=row.is_labeled,
            image_url=s3.get_presigned_url(
                row.image_key,
                base_url=str(request.base_url).rstrip("/"),
            ),
            thumb_url=s3.get_presigned_url(
                row.thumb_key,
                base_url=str(request.base_url).rstrip("/"),
            ),
            filename=Path(row.image_key).name,
            task=dataset.task,
            objects_count=len(annotations),
            annotation_classes=class_catalog,
            annotations=annotations,
            lock_user=row.lock_user,
            lock_until=row.lock_until,
            parse_error=row.parse_error,
        ))

    stats = sample_repo.get_gallery_stats(dataset_id, normalized_split)
    class_counts = sample_repo.get_class_counts(dataset_id)
    classes = [
        GalleryClassDTO(id=index, name=name, count=class_counts.get(index, 0))
        for index, name in enumerate(class_names)
    ]
    return GalleryPageDTO(
        total=total,
        page=page,
        page_size=page_size,
        task=dataset.task,
        labeled_count=stats["labeled"],
        unlabeled_count=stats["unlabeled"],
        classes=classes,
        items=items,
    )


@router.post("/import-zip", response_model=ImportJobDTO, status_code=status.HTTP_202_ACCEPTED)
async def import_dataset_zip(dataset_id: int,
                             background_tasks: BackgroundTasks,
                             file: UploadFile = File(...),
                             user: CurrentUser = Depends(require_dataset_role({"owner"})),
                             dataset=Depends(get_dataset_or_404),
                             import_job_repo=Depends(get_import_job_repo)) -> ImportJobDTO:
    """Принимает ZIP с датасетом, проходит по train/val/test и строит все превью с масками."""
    if not file.filename or Path(file.filename).suffix.lower() != ".zip":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Загрузите ZIP-архив с датасетом",
        )

    zip_path = await spool_upload(file)
    try:
        import_record = import_job_repo.create(user_id=user.id, dataset_id=dataset_id)
        background_tasks.add_task(
            run_existing_dataset_import,
            import_id=import_record.id,
            zip_path=str(zip_path),
            dataset_id=dataset_id,
            task=dataset.task,
        )
    except Exception:
        Path(zip_path).unlink(missing_ok=True)
        raise

    return ImportJobDTO(
        import_id=import_record.id,
        dataset_id=dataset_id,
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


@router.post("/upload-url", response_model=UploadUrlResponse)
def get_upload_url(dataset_id: int,
                   req: UploadUrlRequest,
                   user: CurrentUser = Depends(require_dataset_role({"owner"})),
                   s3: S3Client = Depends(get_s3_client)) -> UploadUrlResponse:
    """Выдаёт presigned PUT ссылку для прямой загрузки кадра во временный префикс S3."""
    try:
        raw_key = incoming_key(dataset_id, req.split, req.filename)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=client_error(exc)) from exc
    url = s3.get_presigned_upload_url(key=raw_key, content_type=req.content_type)
    return UploadUrlResponse(upload_key=raw_key, upload_url=url)


@router.post("/complete-upload", response_model=SampleCardDTO)
def complete_upload(request: Request,
                    dataset_id: int,
                    req: CompleteUploadRequest,
                    user: CurrentUser = Depends(require_dataset_role({"owner"})),
                    dataset=Depends(get_dataset_or_404),
                    s3: S3Client = Depends(get_s3_client),
                    sample_repo=Depends(get_sample_repo)) -> SampleCardDTO:
    """
    Завершает загрузку одиночного кадра:
    конвертирует (heic/webp → jpg), создаёт пустой .txt и превью, регистрирует сэмпл в БД.
    """
    prefix = f"datasets/{int(dataset_id)}/_incoming/"
    if not isinstance(req.upload_key, str) or not req.upload_key.startswith(prefix):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Некорректный ключ загрузки")
    rest = req.upload_key[len(prefix):]
    parts = rest.split("/")
    if len(parts) != 2:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Некорректный ключ загрузки")
    try:
        split_name = clean_split(parts[0])
        clean_filename(parts[1])
        if split_name != clean_split(req.split):
            raise ValueError("Некорректный split")
        s3.safe_path(req.upload_key)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=client_error(exc)) from exc

    raw_bytes = s3.get_bytes(req.upload_key)
    if not raw_bytes:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Загруженный файл не найден в S3")

    orig_name = Path(req.upload_key).name

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
    sample_repo.set_geometries(sample_id=row.id, geometries=[])

    return SampleCardDTO(
        id=row.id,
        dataset_id=dataset_id,
        stem=row.stem,
        split=row.split,
        status=row.status,
        is_labeled=row.is_labeled,
        image_url=s3.get_presigned_url(
            s3_img_key,
            base_url=str(request.base_url).rstrip("/"),
        ),
        thumb_url=s3.get_presigned_url(
            s3_thb_key,
            base_url=str(request.base_url).rstrip("/"),
        ),
    )


@router.delete("/{sample_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sample(dataset_id: int,
                  sample_id: int,
                  user: CurrentUser = Depends(require_dataset_role({"owner"})),
                  s3: S3Client = Depends(get_s3_client),
                  sample_repo=Depends(get_sample_repo)) -> None:
    """Удаляет сэмпл из БД и чистит его файлы (оригинал, .txt, превью) из S3."""
    row = sample_repo.get_by_id(dataset_id=dataset_id, sample_id=sample_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Кадр не найден")

    s3.delete_many([row.image_key, row.label_key, row.thumb_key])
    sample_repo.delete(sample_id=sample_id)