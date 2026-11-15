from datetime import datetime

from pydantic import BaseModel, Field


class SampleCommentCreateDTO(BaseModel):
    body: str = Field(min_length=1, max_length=2000)
    parent_id: int | None = None
    annotation_index: int | None = Field(default=None, ge=0)


class SampleCommentDTO(BaseModel):
    id: int
    sample_id: int
    user_id: int
    author_name: str
    body: str
    parent_id: int | None = None
    annotation_index: int | None = None
    resolved: bool
    created_at: datetime
