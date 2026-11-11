# apps/api/app/schemas/sample.py

import logging
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field

from apps.api.app.schemas.annotation import AnnotationItemDTO


class GalleryClassDTO(BaseModel):
    id: int
    name: str
    count: int

logger = logging.getLogger(__name__)


class UploadUrlRequest(BaseModel):
    filename: str
    split: str = "train"
    content_type: str = "image/jpeg"


class UploadUrlResponse(BaseModel):
    upload_key: str
    upload_url: str


class CompleteUploadRequest(BaseModel):
    upload_key: str
    split: str = "train"


class SampleCardDTO(BaseModel):
    id: int
    sample_id: Optional[int] = None
    dataset_id: int
    stem: str
    split: str
    status: str
    is_labeled: bool
    image_url: str          # покой — чистый кадр
    thumb_url: str          # hover — тумба с масками (Drawer)
    filename: str = ""
    task: str = ""
    objects_count: int = 0
    annotation_classes: List[GalleryClassDTO] = Field(default_factory=list)
    annotations: List[AnnotationItemDTO] = Field(default_factory=list)
    lock_user: Optional[int] = None
    lock_until: Optional[datetime] = None
    parse_error: Optional[str] = None


class GalleryPageDTO(BaseModel):
    total: int
    page: int
    page_size: int
    task: str = ""
    labeled_count: int = 0
    unlabeled_count: int = 0
    classes: List[GalleryClassDTO] = Field(default_factory=list)
    items: List[SampleCardDTO] = Field(default_factory=list)