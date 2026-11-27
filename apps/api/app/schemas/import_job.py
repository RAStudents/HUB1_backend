from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ImportJobDTO(BaseModel):
    import_id: int
    dataset_id: str | None = None
    status: Literal["queued", "processing", "confirmation_required", "completed", "failed"]
    stage: Literal[
        "queued",
        "processing",
        "extracting",
        "normalizing",
        "copying",
        "discovering",
        "confirmation_required",
        "importing",
        "finalizing",
        "building_gallery",
        "completed",
        "failed",
    ]
    progress: int
    total_samples: int
    processed_samples: int
    imported_samples: int
    parse_errors: int
    warning: str | None = None
    error: str | None = None
    created_at: datetime | None = None
