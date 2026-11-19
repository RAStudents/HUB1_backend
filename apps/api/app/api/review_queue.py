from collections import Counter
from datetime import timezone
from pathlib import Path
from typing import Literal

from acmenra_cv import TaskType
from fastapi import APIRouter, Depends, Query, Request

from apps.api.app.deps import (
    DatasetId,
    CurrentUser, get_current_user, get_class_repo, get_dataset_or_404,
    get_review_repo, get_s3_client, get_sample_repo, require_dataset_role,
)
from apps.api.app.schemas.review import (
    ReviewDatasetCountDTO, ReviewLabelerDTO, ReviewQueueDTO, ReviewQueueItemDTO, ReviewSummaryDTO,
)
from apps.api.app.schemas.sample import GalleryClassDTO
from core.infrastructure.cv.labels import parse_label_file
from core.infrastructure.cv.mapper import instances_to_dtos
from core.infrastructure.media.scratch import scratch_file


router = APIRouter(tags=["review"])


@router.get("/review/summary", response_model=ReviewSummaryDTO)
def review_summary(user: CurrentUser = Depends(get_current_user),
                   reviews=Depends(get_review_repo)):
    rows = reviews.summary(user.id)
    return ReviewSummaryDTO(
        total=sum(row.pending_count for row in rows),
        datasets=[ReviewDatasetCountDTO(**dict(row._mapping)) for row in rows],
    )


@router.get("/datasets/{dataset_id}/review-queue", response_model=ReviewQueueDTO)
def review_queue(request: Request,
                 dataset_id: DatasetId,
                 labeler_id: int | None = Query(None, ge=1, description="Пользователь, отправивший кадр на проверку"),
                 sort: Literal["oldest", "newest"] = "oldest",
                 page: int = Query(1, ge=1),
                 page_size: int = Query(24, ge=1, le=100),
                 _user: CurrentUser = Depends(require_dataset_role({"owner"})),
                 dataset=Depends(get_dataset_or_404),
                 reviews=Depends(get_review_repo),
                 samples=Depends(get_sample_repo),
                 classes=Depends(get_class_repo),
                 s3=Depends(get_s3_client)):
    total, queue_total, labelers, rows = reviews.queue(
        dataset_id, labeler_id, sort, (page - 1) * page_size, page_size,
    )
    names = classes.get_names(dataset_id)
    task = TaskType(dataset.task)
    base_url = str(request.base_url).rstrip("/")
    items = []
    for row in rows:
        annotations = samples.get_geometries(row.geometry_json)
        if not row.geometry_json:
            raw_label = s3.get_bytes(row.label_key)
            if raw_label:
                with scratch_file(suffix=".txt", data=raw_label) as path:
                    instances = parse_label_file(path=path, class_names=names, task=task)
                annotations = [item.model_dump(mode="json") for item in instances_to_dtos(instances, task)]
        counts = Counter(item["class_id"] for item in annotations)
        for item in annotations:
            class_id = item["class_id"]
            if 0 <= class_id < len(names):
                item["class_name"] = names[class_id]
        submitted_at = row.submitted_at
        if submitted_at is not None and submitted_at.tzinfo is None:
            submitted_at = submitted_at.replace(tzinfo=timezone.utc)
        items.append(ReviewQueueItemDTO(
            id=row.id, sample_id=row.id, dataset_id=dataset.public_id, stem=row.stem,
            split=row.split, status=row.status, is_labeled=row.is_labeled,
            image_url=s3.get_presigned_url(row.image_key, base_url=base_url),
            thumb_url=s3.get_presigned_url(row.thumb_key, base_url=base_url),
            filename=Path(row.image_key).name, task=dataset.task,
            objects_count=len(annotations), annotations=annotations,
            annotation_classes=[GalleryClassDTO(
                id=class_id, name=names[class_id] if 0 <= class_id < len(names) else f"Класс {class_id}",
                count=count,
            ) for class_id, count in sorted(counts.items())],
            lock_user=row.lock_user, lock_until=row.lock_until, parse_error=row.parse_error,
            submitted_by_id=row.submitted_by_id, submitted_by_name=row.submitted_by_name,
            submitted_at=submitted_at,
        ))
    return ReviewQueueDTO(
        dataset_id=dataset.public_id, dataset_name=dataset.name, total=total, queue_total=queue_total,
        page=page, page_size=page_size, sort=sort,
        labelers=[ReviewLabelerDTO(**dict(row._mapping)) for row in labelers], items=items,
    )
