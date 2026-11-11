from datetime import datetime

from pydantic import BaseModel


class SampleLockDTO(BaseModel):
    sample_id: int
    lock_user: int | None
    lock_until: datetime | None
