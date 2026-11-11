# core/domain/dataset.py

import logging
from datetime import datetime, timezone

from acmenra_cv import TaskType


logger = logging.getLogger(__name__)


class Dataset:
    def __init__(self,
                 id: int | None,
                 name: str,
                 task: TaskType,
                 owner_id: int,
                 description: str | None = None,
                 is_private: bool = True,
                 created_at: datetime | None = None):
        self.id = id
        self.name = name
        self.task = task
        self.owner_id = owner_id
        self.description = description
        self.is_private = is_private
        self.created_at = created_at or datetime.now(timezone.utc)

    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Имя датасета не может быть пустым")
        self._name = value.strip()

    @property
    def task(self) -> TaskType:
        return self._task

    @task.setter
    def task(self, value: TaskType | str) -> None:
        if isinstance(value, str):
            value = TaskType(value.lower())
        if not isinstance(value, TaskType):
            raise TypeError("Некорректный тип задачи датасета")
        self._task = value