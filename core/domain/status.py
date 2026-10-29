# core/domain/status.py
from core.domain.enums import SampleStatusEnum


class StatusTransitionValidator:
    ALLOWED_TRANSITIONS = {
        SampleStatusEnum.UNLABELED: {SampleStatusEnum.IN_PROGRESS},
        SampleStatusEnum.IN_PROGRESS: {SampleStatusEnum.IN_REVIEW, SampleStatusEnum.UNLABELED},
        SampleStatusEnum.IN_REVIEW: {SampleStatusEnum.ACCEPTED, SampleStatusEnum.REJECTED},
        SampleStatusEnum.REJECTED: {SampleStatusEnum.IN_PROGRESS},
        SampleStatusEnum.ACCEPTED: {SampleStatusEnum.IN_PROGRESS},  # Если владелец вернул с ревью
    }

    @classmethod
    def can_transition(cls, current: SampleStatusEnum, target: SampleStatusEnum) -> bool:
        if current == target:
            return True
        return target in cls.ALLOWED_TRANSITIONS.get(current, set())