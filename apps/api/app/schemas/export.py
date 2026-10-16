# apps/api/app/schemas/export.py
from typing import Optional
from pydantic import BaseModel


class ExportStatusDTO(BaseModel):
    export_id: int
    status: str
    exported_samples: int = 0
    download_url: Optional[str] = None
    error: Optional[str] = None