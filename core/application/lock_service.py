from datetime import datetime, timedelta, timezone
from typing import Any


LOCK_TTL = timedelta(minutes=20)


class LockService:
    def __init__(
        self,
        sample_repo: Any,
        membership_repo: Any,
        event_repo: Any,
    ):
        self.samples = sample_repo
        self.memberships = membership_repo
        self.events = event_repo

    def acquire(self, dataset_id: int, sample_id: int, user_id: int) -> dict:
        role = self.memberships.get_user_role(dataset_id, user_id)
        if role not in {"owner", "labeler"}:
            raise PermissionError("Недостаточно прав для редактирования кадра")

        sample = self._get_sample(dataset_id, sample_id)
        if role == "labeler" and sample.status == "accepted":
            raise PermissionError(
                "Принятый кадр может открыть для редактирования только владелец"
            )
        if sample.status == "in_review":
            raise ValueError("Сначала завершите проверку кадра")

        now = datetime.now(timezone.utc)
        current_lock_until = self._as_utc(sample.lock_until)
        if (
            sample.lock_user is not None
            and current_lock_until is not None
            and current_lock_until > now
            and sample.lock_user != user_id
        ):
            raise ValueError("Кадр уже редактируется другим пользователем")

        lock_until = now + LOCK_TTL
        if not self.samples.acquire_sample_lock(
            dataset_id=dataset_id,
            sample_id=sample_id,
            user_id=user_id,
            lock_until=lock_until,
            now=now,
        ):
            raise ValueError("Кадр уже редактируется другим пользователем")

        if sample.lock_user != user_id:
            self._log(dataset_id, sample_id, user_id, "sample_lock_acquired")
        return self._lock_state(dataset_id, sample_id)

    def renew(self, dataset_id: int, sample_id: int, user_id: int) -> dict:
        role = self.memberships.get_user_role(dataset_id, user_id)
        if role not in {"owner", "labeler"}:
            raise PermissionError("Недостаточно прав для редактирования кадра")

        sample = self._get_sample(dataset_id, sample_id)
        if role == "labeler" and sample.status != "in_progress":
            raise PermissionError("Разметчик может изменять только кадр в работе")
        now = datetime.now(timezone.utc)
        lock_until = self._as_utc(sample.lock_until)
        if (
            sample.lock_user != user_id
            or lock_until is None
            or lock_until <= now
        ):
            raise PermissionError("Нет активной блокировки этого кадра")

        if not self.samples.acquire_sample_lock(
            dataset_id=dataset_id,
            sample_id=sample_id,
            user_id=user_id,
            lock_until=now + LOCK_TTL,
            now=now,
        ):
            raise PermissionError("Блокировка кадра больше не принадлежит вам")
        return self._lock_state(dataset_id, sample_id)

    def release(self, dataset_id: int, sample_id: int, user_id: int) -> dict:
        role = self.memberships.get_user_role(dataset_id, user_id)
        if role not in {"owner", "labeler"}:
            raise PermissionError("Недостаточно прав для снятия блокировки")

        sample = self._get_sample(dataset_id, sample_id)
        if sample.lock_user != user_id:
            raise PermissionError("Снять блокировку может только её владелец")
        if not self.samples.release_sample_lock(
            dataset_id=dataset_id,
            sample_id=sample_id,
            user_id=user_id,
        ):
            raise ValueError("Блокировка кадра уже снята")

        self._log(dataset_id, sample_id, user_id, "sample_lock_released")
        return self._lock_state(dataset_id, sample_id)

    def force_release(
        self,
        dataset_id: int,
        sample_id: int,
        user_id: int,
    ) -> dict:
        if self.memberships.get_user_role(dataset_id, user_id) != "owner":
            raise PermissionError("Снять блокировку принудительно может только владелец")

        sample = self._get_sample(dataset_id, sample_id)
        if sample.lock_user is None:
            raise ValueError("У кадра нет активной блокировки")
        if not self.samples.release_sample_lock(
            dataset_id=dataset_id,
            sample_id=sample_id,
        ):
            raise ValueError("Блокировка кадра уже снята")

        self._log(dataset_id, sample_id, user_id, "sample_lock_force_released")
        return self._lock_state(dataset_id, sample_id)

    def _get_sample(self, dataset_id: int, sample_id: int):
        sample = self.samples.get_by_id(dataset_id=dataset_id, sample_id=sample_id)
        if sample is None:
            raise LookupError("Кадр не найден")
        return sample

    def _lock_state(self, dataset_id: int, sample_id: int) -> dict:
        sample = self._get_sample(dataset_id, sample_id)
        return {
            "sample_id": sample_id,
            "lock_user": sample.lock_user,
            "lock_until": self._as_utc(sample.lock_until),
        }

    def _log(
        self,
        dataset_id: int,
        sample_id: int,
        user_id: int,
        action: str,
    ) -> None:
        if self.events is not None:
            self.events.log(
                dataset_id=dataset_id,
                sample_id=sample_id,
                user_id=user_id,
                action=action,
            )

    @staticmethod
    def _as_utc(value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
