# core/domain/enums.py
from enum import Enum


class TaskTypeEnum(str, Enum):
    DETECT = "detect"
    OBB = "obb"
    SEGMENT = "segment"


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