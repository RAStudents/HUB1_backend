from typing import Literal

from pydantic import BaseModel


class ReviewDecisionDTO(BaseModel):
    decision: Literal["accepted", "rejected"]


class ReviewStatusDTO(BaseModel):
    sample_id: int
    status: str
