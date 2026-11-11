# apps/api/app/schemas/export.py

import logging
from typing import Literal, Optional
from pydantic import BaseModel


logger = logging.getLogger(__name__)


class ExportStatusDTO(BaseModel):
    export_id: int
    status: str
    stage: str = "processing"
    exported_samples: int = 0
    total_samples: int = 0
    progress: int = 0
    download_url: Optional[str] = None
    error: Optional[str] = None


class ExportRequestDTO(BaseModel):
    class_ids: list[int] | None = None
    splits: list[Literal["train", "val", "test"]] | None = None


class ExportClassDTO(BaseModel):
    id: int
    name: str
    count: int = 0