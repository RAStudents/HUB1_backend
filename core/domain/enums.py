# core/domain/enums.py

import logging
from enum import Enum


logger = logging.getLogger(__name__)


class SplitEnum(str, Enum):
    TRAIN = "train"
    VAL = "val"
    TEST = "test"


class RoleEnum(str, Enum):
    OWNER = "owner"
    LABELER = "labeler"
    OBSERVER = "observer"


class SampleStatusEnum(str, Enum):
    UNLABELED = "unlabeled"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"  # "На доработку" по ТЗ