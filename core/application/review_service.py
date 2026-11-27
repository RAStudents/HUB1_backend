# core/application/review_service.py

import logging
from typing import Any, Literal

from core.domain.enums import SampleStatusEnum
from core.domain.status import StatusTransitionValidator


logger = logging.getLogger(__name__)


ReviewDecision = Literal["accepted", "rejected"]


class ReviewService:
    def __init__(self,
                 sample_repo: Any,
                 membership_repo: Any,
                 event_repo: Any | None = None):
        self.samples = sample_repo
        self.memberships = membership_repo
        self.events = event_repo

    def submit_for_review(self,
                          dataset_id: int,
                          sample_id: int,
                          user_id: int) -> str:
        role = self.memberships.get_user_role(dataset_id=dataset_id, user_id=user_id)
        if role not in {"owner", "labeler"}:
            raise PermissionError("Недостаточно прав для отправки кадра на проверку")

        sample = self.samples.get_by_id(dataset_id=dataset_id, sample_id=sample_id)
        if sample is None:
            raise LookupError("Кадр не найден")
        if sample.parse_error:
            raise ValueError("Сначала исправьте ошибку разбора разметки")

        current = SampleStatusEnum(sample.status)
        target = SampleStatusEnum.IN_REVIEW
        if current != SampleStatusEnum.IN_PROGRESS or not StatusTransitionValidator.can_transition(current, target):
            raise ValueError("На проверку можно отправить только кадр в работе")

        if not self.samples.set_status_if(sample_id=sample_id, expected=current.value, status=target.value):
            raise ValueError("Статус кадра уже изменился")
        self._log(dataset_id, sample_id, user_id, "sample_submitted_for_review")
        return target.value

    def decide(self,
               dataset_id: int,
               sample_id: int,
               user_id: int,
               decision: ReviewDecision) -> str:
        role = self.memberships.get_user_role(dataset_id=dataset_id, user_id=user_id)
        if role != "owner":
            raise PermissionError("Только владелец датасета может проверять кадры")

        sample = self.samples.get_by_id(dataset_id=dataset_id, sample_id=sample_id)
        if sample is None:
            raise LookupError("Кадр не найден")

        current = SampleStatusEnum(sample.status)
        target = SampleStatusEnum(decision)
        if current != SampleStatusEnum.IN_REVIEW or not StatusTransitionValidator.can_transition(current, target):
            raise ValueError("Решение можно принять только для кадра на проверке")

        if not self.samples.set_status_if(sample_id=sample_id, expected=current.value, status=target.value):
            raise ValueError("Статус кадра уже изменился")
        self._log(dataset_id, sample_id, user_id, f"sample_{target.value}")
        return target.value

    def reopen_for_revision(self,
                            dataset_id: int,
                            sample_id: int,
                            user_id: int) -> str:
        role = self.memberships.get_user_role(dataset_id=dataset_id, user_id=user_id)
        if role not in {"owner", "labeler"}:
            raise PermissionError("Недостаточно прав для доработки кадра")

        sample = self.samples.get_by_id(dataset_id=dataset_id, sample_id=sample_id)
        if sample is None:
            raise LookupError("Кадр не найден")

        current = SampleStatusEnum(sample.status)
        target = SampleStatusEnum.IN_PROGRESS
        if current != SampleStatusEnum.REJECTED or not StatusTransitionValidator.can_transition(current, target):
            raise ValueError("На доработку можно вернуть только отклонённый кадр")

        if not self.samples.set_status_if(sample_id=sample_id, expected=current.value, status=target.value):
            raise ValueError("Статус кадра уже изменился")
        self._log(dataset_id, sample_id, user_id, "sample_reopened_for_revision")
        return target.value

    def change_status(self,
                      dataset_id: int,
                      sample_id: int,
                      user_id: int,
                      new_status: str) -> str:
        """Меняет статус кадра владельцем или наблюдателем без права править геометрию."""
        role = self.memberships.get_user_role(dataset_id=dataset_id, user_id=user_id)
        if role != "owner":
            raise PermissionError("Менять статус может только владелец датасета")

        sample = self.samples.get_by_id(dataset_id=dataset_id, sample_id=sample_id)
        if sample is None:
            raise LookupError("Кадр не найден")

        try:
            current = SampleStatusEnum(sample.status)
            target = SampleStatusEnum(new_status)
        except ValueError as exc:
            raise ValueError("Неизвестный статус кадра") from exc

        if current == target:
            return target.value
        if not StatusTransitionValidator.can_transition(current, target):
            raise ValueError(f"Недопустимый переход статуса: {current.value} → {target.value}")
        if target == SampleStatusEnum.IN_REVIEW and sample.parse_error:
            raise ValueError("Сначала исправьте ошибку разбора разметки")
        if not self.samples.set_status_if(
            sample_id=sample_id,
            expected=current.value,
            status=target.value,
        ):
            raise ValueError("Статус кадра уже изменился")
        self._log(dataset_id, sample_id, user_id, f"sample_status_changed_to_{target.value}")
        return target.value

    def _log(self,
             dataset_id: int,
             sample_id: int,
             user_id: int,
             action: str) -> None:
        if self.events is not None:
            self.events.log(
                dataset_id=dataset_id,
                sample_id=sample_id,
                user_id=user_id,
                action=action,
            )
