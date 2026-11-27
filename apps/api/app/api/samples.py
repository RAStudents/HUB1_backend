# apps/api/app/api/samples.py

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from acmenra_cv import TaskType
from collections import Counter

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile, status

from apps.api.app.deps import (
    DatasetId,
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
    SampleEditorDTO,
    SampleCardDTO,
    SampleSplitUpdateDTO,
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
from core.infrastructure.s3.keys import (
    clean_filename, clean_split, dataset_storage_prefix, dataset_storage_prefixes,
    image_key, incoming_key, label_key, thumb_key,
)


logger = logging.getLogger(__name__)


router = APIRouter(prefix="/datasets/{dataset_id}/samples", tags=["samples"])

_DIRECT_UPLOAD_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".bmp", ".tiff", ".tif"}
_MAX_DIRECT_UPLOAD_FILES = 100


@router.get("", response_model=GalleryPageDTO)
def list_gallery_samples(request: Request,
                         dataset_id: DatasetId,
                         split: Optional[str] = Query(None, description="train | val | test | None (все)"),
                         sample_status: Optional[str] = Query(None, alias="status"),
                         search: Optional[str] = Query(None, max_length=255),
                         labeled: Optional[bool] = Query(None),
                         object_count: Optional[str] = Query(None, pattern="^(none|one|multiple)$"),
                         class_ids: list[int] | None = Query(None),
                         page: int = Query(1, ge=1),
                         page_size: int = Query(24, ge=1, le=100),
                         anchor_sample_id: int | None = Query(None, ge=1),
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

    try:
        total, rows, offset = sample_repo.paginate_gallery(
            dataset_id=dataset_id,
            split=normalized_split,
            status=sample_status,
            labeled=labeled,
            search=search.strip() if search else None,
            object_count=object_count,
            class_ids=class_ids or [],
            offset=(page - 1) * page_size,
            limit=page_size,
            anchor_sample_id=anchor_sample_id,
        )
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Кадр не найден.") from exc

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
            dataset_id=dataset.public_id,
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
        page=offset // page_size + 1,
        page_size=page_size,
        task=dataset.task,
        labeled_count=stats["labeled"],
        unlabeled_count=stats["unlabeled"],
        classes=classes,
        items=items,
    )


@router.get("/{sample_id}", response_model=SampleEditorDTO)
def get_sample_for_editor(request: Request,
                          dataset_id: DatasetId,
                          sample_id: int,
                          user: CurrentUser = Depends(
                              require_dataset_role({"owner", "labeler", "observer"})
                          ),
                          dataset=Depends(get_dataset_or_404),
                          s3: S3Client = Depends(get_s3_client),
                          sample_repo=Depends(get_sample_repo),
                          class_repo=Depends(get_class_repo)) -> SampleEditorDTO:
    """Возвращает кадр и каталог классов для инспектора/редактора."""
    row = sample_repo.get_by_id(dataset_id=dataset_id, sample_id=sample_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Кадр не найден")

    class_names = class_repo.get_names(dataset_id)
    class_counts = sample_repo.get_class_counts(dataset_id)
    geometries = sample_repo.get_geometries_for_sample(sample_id)
    base_url = str(request.base_url).rstrip("/")
    sample = SampleCardDTO(
        id=row.id,
        sample_id=row.id,
        dataset_id=dataset.public_id,
        stem=row.stem,
        split=row.split,
        status=row.status,
        is_labeled=row.is_labeled,
        image_url=s3.get_presigned_url(row.image_key, base_url=base_url),
        thumb_url=s3.get_presigned_url(row.thumb_key, base_url=base_url),
        filename=Path(row.image_key).name,
        task=dataset.task,
        objects_count=len(geometries),
        annotations=geometries,
        lock_user=row.lock_user,
        lock_until=row.lock_until,
        parse_error=row.parse_error,
    )
    classes = [
        GalleryClassDTO(id=index, name=name, count=class_counts.get(index, 0))
        for index, name in enumerate(class_names)
    ]
    return SampleEditorDTO(sample=sample, classes=classes)


@router.patch("/{sample_id}/split", response_model=SampleCardDTO)
def update_sample_split(request: Request,
                        dataset_id: DatasetId,
                        sample_id: int,
                        payload: SampleSplitUpdateDTO,
                        user: CurrentUser = Depends(require_dataset_role({"owner", "labeler"})),
                        dataset=Depends(get_dataset_or_404),
                        s3: S3Client = Depends(get_s3_client),
                        sample_repo=Depends(get_sample_repo)) -> SampleCardDTO:
    row = sample_repo.get_by_id(dataset_id, sample_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Кадр не найден")
    try:
        split_name = clean_split(payload.split)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=client_error(exc)) from exc
    if split_name == row.split:
        return SampleCardDTO(
            id=row.id, sample_id=row.id, dataset_id=dataset.public_id, stem=row.stem,
            split=row.split, status=row.status, is_labeled=row.is_labeled,
            image_url=s3.get_presigned_url(row.image_key, base_url=str(request.base_url).rstrip("/")),
            thumb_url=s3.get_presigned_url(row.thumb_key, base_url=str(request.base_url).rstrip("/")),
            filename=Path(row.image_key).name, task=dataset.task,
        )
    lock_until = row.lock_until
    if lock_until is not None and lock_until.tzinfo is None:
        lock_until = lock_until.replace(tzinfo=timezone.utc)
    if row.lock_user not in (None, user.id) and lock_until and lock_until > datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Кадр редактирует другой пользователь")
    if sample_repo.list_by_stem(dataset_id, split_name, row.stem):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="В выбранном split уже есть кадр с таким именем")

    prefix = dataset_storage_prefix(dataset)
    new_image_key = image_key(prefix, split_name, Path(row.image_key).name)
    new_label_key = label_key(prefix, split_name, row.stem)
    new_thumb_key = thumb_key(prefix, split_name, row.stem)
    old_keys = [row.image_key, row.label_key, row.thumb_key]
    new_keys = [new_image_key, new_label_key, new_thumb_key]
    content = [s3.get_bytes(key) for key in old_keys]
    if any(value is None for value in content):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файлы кадра не найдены в хранилище")
    created_keys = []
    try:
        for key, data, mime in zip(new_keys, content, ("image/jpeg", "text/plain", "image/jpeg")):
            s3.put_bytes(key, data, content_type=mime)
            created_keys.append(key)
        sample_repo.update_split_and_keys(dataset_id, sample_id, split_name, *new_keys)
    except Exception:
        s3.delete_many(created_keys)
        raise
    s3.delete_many(old_keys)
    return SampleCardDTO(
        id=row.id, sample_id=row.id, dataset_id=dataset.public_id, stem=row.stem,
        split=split_name, status=row.status, is_labeled=row.is_labeled,
        image_url=s3.get_presigned_url(new_image_key, base_url=str(request.base_url).rstrip("/")),
        thumb_url=s3.get_presigned_url(new_thumb_key, base_url=str(request.base_url).rstrip("/")),
        filename=Path(new_image_key).name, task=dataset.task,
    )


@router.post("/import-zip", response_model=ImportJobDTO, status_code=status.HTTP_202_ACCEPTED)
async def import_dataset_zip(dataset_id: DatasetId,
                             background_tasks: BackgroundTasks,
                             file: UploadFile = File(...),
                             allow_unlabeled: bool = Form(False),
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
            allow_unlabeled=allow_unlabeled,
        )
    except Exception:
        Path(zip_path).unlink(missing_ok=True)
        raise

    return ImportJobDTO(
        import_id=import_record.id,
        dataset_id=dataset.public_id,
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
def get_upload_url(dataset_id: DatasetId,
                   req: UploadUrlRequest,
                   user: CurrentUser = Depends(require_dataset_role({"owner"})),
                   dataset=Depends(get_dataset_or_404),
                   s3: S3Client = Depends(get_s3_client)) -> UploadUrlResponse:
    """Выдаёт presigned PUT ссылку для прямой загрузки кадра во временный префикс S3."""
    try:
        raw_key = incoming_key(dataset_storage_prefix(dataset), req.split, req.filename)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=client_error(exc)) from exc
    url = s3.get_presigned_upload_url(key=raw_key, content_type=req.content_type)
    return UploadUrlResponse(upload_key=raw_key, upload_url=url)


@router.post("/upload", response_model=list[SampleCardDTO], status_code=status.HTTP_201_CREATED)
async def upload_samples(request: Request,
                         dataset_id: DatasetId,
                         files: list[UploadFile] = File(...),
                         split: str = Form("train"),
                         user: CurrentUser = Depends(require_dataset_role({"owner"})),
                         dataset=Depends(get_dataset_or_404),
                         s3: S3Client = Depends(get_s3_client),
                         sample_repo=Depends(get_sample_repo)) -> list[SampleCardDTO]:
    """Загружает изображения прямо в API и добавляет их в существующий датасет."""
    if not files:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Выберите хотя бы один кадр")
    if len(files) > _MAX_DIRECT_UPLOAD_FILES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"За одну загрузку можно добавить не более {_MAX_DIRECT_UPLOAD_FILES} кадров",
        )

    try:
        split_name = clean_split(split)
        prepared = []
        incoming_stems: set[str] = set()
        for upload in files:
            filename = clean_filename(upload.filename or "")
            if Path(filename).suffix.lower() not in _DIRECT_UPLOAD_EXTENSIONS:
                raise ValueError(f"Неподдерживаемый формат изображения: {Path(filename).suffix}")
            content = await upload.read(25 * 1024 * 1024 + 1)
            if len(content) > 25 * 1024 * 1024:
                raise HTTPException(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    detail=f"Изображение {filename} превышает ограничение 25 МБ",
                )
            with scratch_file(suffix=Path(filename).suffix, data=content) as source_path:
                image_bytes, normalized_name, content_type = normalize_image_file(source_path)
            stem = Path(normalized_name).stem
            if stem in incoming_stems or sample_repo.list_by_stem(dataset_id, split_name, stem):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Кадр с именем {stem} уже существует в сплите {split_name}",
                )
            incoming_stems.add(stem)
            with scratch_file(suffix=Path(normalized_name).suffix, data=image_bytes) as normalized_path:
                thumb_bytes = render_thumbnail_bytes(
                    image_path=normalized_path,
                    instances=[],
                    task=TaskType(dataset.task),
                )
            prepared.append((stem, normalized_name, content_type, image_bytes, thumb_bytes))
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=client_error(exc)) from exc
    finally:
        for upload in files:
            await upload.close()

    created: list[SampleCardDTO] = []
    created_keys: list[str] = []
    created_sample_ids: list[int] = []
    prefix = dataset_storage_prefix(dataset)
    try:
        for stem, filename, content_type, image_bytes, thumb_bytes in prepared:
            s3_img_key = image_key(prefix, split_name, filename)
            s3_lbl_key = label_key(prefix, split_name, stem)
            s3_thb_key = thumb_key(prefix, split_name, stem)
            s3.put_bytes(s3_img_key, image_bytes, content_type=content_type)
            created_keys.append(s3_img_key)
            s3.put_bytes(s3_lbl_key, b"", content_type="text/plain")
            created_keys.append(s3_lbl_key)
            s3.put_bytes(s3_thb_key, thumb_bytes, content_type="image/jpeg")
            created_keys.append(s3_thb_key)
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
            created_sample_ids.append(row.id)
            sample_repo.set_geometries(sample_id=row.id, geometries=[])
            base_url = str(request.base_url).rstrip("/")
            created.append(SampleCardDTO(
                id=row.id,
                sample_id=row.id,
                dataset_id=dataset.public_id,
                stem=row.stem,
                split=row.split,
                status=row.status,
                is_labeled=row.is_labeled,
                image_url=s3.get_presigned_url(s3_img_key, base_url=base_url),
                thumb_url=s3.get_presigned_url(s3_thb_key, base_url=base_url),
                filename=Path(s3_img_key).name,
                task=dataset.task,
            ))
    except Exception:
        for sample_id in created_sample_ids:
            sample_repo.delete(sample_id)
        s3.delete_many(created_keys)
        raise
    return created


@router.post("/complete-upload", response_model=SampleCardDTO)
def complete_upload(request: Request,
                    dataset_id: DatasetId,
                    req: CompleteUploadRequest,
                    user: CurrentUser = Depends(require_dataset_role({"owner"})),
                    dataset=Depends(get_dataset_or_404),
                    s3: S3Client = Depends(get_s3_client),
                    sample_repo=Depends(get_sample_repo)) -> SampleCardDTO:
    """
    Завершает загрузку одиночного кадра:
    конвертирует (heic/webp → jpg), создаёт пустой .txt и превью, регистрирует сэмпл в БД.
    """
    prefixes = dataset_storage_prefixes(dataset)
    pending_prefixes = (f"{root}/_incoming/" for root in prefixes)
    pending_prefix = next((root for root in pending_prefixes if req.upload_key.startswith(root)), None)
    if pending_prefix is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Некорректный ключ загрузки")
    rest = req.upload_key[len(pending_prefix):]
    parts = rest.split("/")
    if len(parts) != 2:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Некорректный ключ загрузки")
    try:
        split_name = clean_split(parts[0])
        clean_filename(parts[1])
        if split_name != clean_split(req.split):
            raise ValueError("Некорректный split")
        s3.validate_key(req.upload_key)
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

    prefix = prefixes[0]
    s3_img_key = image_key(prefix, split_name, norm_filename)
    s3_lbl_key = label_key(prefix, split_name, stem)
    s3_thb_key = thumb_key(prefix, split_name, stem)

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
        dataset_id=dataset.public_id,
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
def delete_sample(dataset_id: DatasetId,
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
