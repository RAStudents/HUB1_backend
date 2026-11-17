# apps/api/app/schemas/review.py

import logging
from typing import Literal

from pydantic import BaseModel


logger = logging.getLogger(__name__)


class ReviewDecisionDTO(BaseModel):
    decision: Literal["accepted", "rejected"]


class SampleStatusUpdateDTO(BaseModel):
    status: Literal["unlabeled", "in_progress", "in_review", "accepted", "rejected"]


class ReviewStatusDTO(BaseModel):
    sample_id: int
    status: str
