import logging
from datetime import datetime, timedelta, timezone
from typing import Any


logger = logging.getLogger(__name__)

LOCK_TTL = timedelta(minutes=20)


def as_utc(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class LockService:
    def __init__(self, sample_repo: Any, membership_repo: Any):
        self.samples = sample_repo
        self.memberships = membership_repo

    def acquire(self, dataset_id: int, sample_id: int, user_id: int) -> datetime:
        self._require_editor(dataset_id, user_id)
        sample = self._sample(dataset_id, sample_id)
        now = datetime.now(timezone.utc)
        if self._held_by_other(sample, user_id, now):
            raise PermissionError("Кадр сейчас занят другим пользователем")
        until = now + LOCK_TTL
        self.samples.lock_sample(sample_id=sample.id, user_id=user_id, lock_until=until)
        return until

    def release(self, dataset_id: int, sample_id: int, user_id: int) -> None:
        role = self._require_editor(dataset_id, user_id)
        sample = self._sample(dataset_id, sample_id)
        if sample.lock_user not in (None, user_id) and role != "owner":
            raise PermissionError("Снять чужую блокировку может только владелец")
        self.samples.unlock_sample(sample.id)

    def _sample(self, dataset_id: int, sample_id: int):
        sample = self.samples.get_by_id(dataset_id=dataset_id, sample_id=sample_id)
        if sample is None:
            raise LookupError("Кадр не найден")
        return sample

    def _require_editor(self, dataset_id: int, user_id: int) -> str:
        role = self.memberships.get_user_role(dataset_id=dataset_id, user_id=user_id)
        if role not in {"owner", "labeler"}:
            raise PermissionError("Недостаточно прав")
        return role

    @staticmethod
    def _held_by_other(sample, user_id: int, now: datetime) -> bool:
        until = as_utc(sample.lock_until)
        return bool(
            sample.lock_user
            and sample.lock_user != user_id
            and until is not None
            and until > now
        )