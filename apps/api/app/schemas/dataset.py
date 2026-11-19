# apps/api/app/schemas/dataset.py

import logging
from typing import Literal

from pydantic import BaseModel, Field


logger = logging.getLogger(__name__)


class CreateDatasetRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    task: Literal["detect", "obb", "segment"] = "segment"
    description: str | None = Field(default=None, max_length=2000)
    is_private: bool = True
    classes: list[str] | None = Field(default=None, max_length=200)