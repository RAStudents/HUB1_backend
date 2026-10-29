# core/application/dataset_service.py
from typing import Any, List

from core.domain.enums import TaskTypeEnum

_DEFAULT_CLASSES = ["object_a", "object_b"]


class DatasetService:
    def __init__(self, dataset_repo: Any, class_repo: Any, membership_repo: Any):
        self.datasets = dataset_repo
        self.classes = class_repo
        self.memberships = membership_repo

    def create_dataset(
        self,
        name: str,
        task: Any,
        owner_id: int,
        description: str | None = None,
        is_private: bool = True,
        initial_classes: List[str] | None = None,
    ) -> int:
        """
        Создаёт датасет, привязывает владельца и сохраняет список классов.

        Принимает task как строку или Enum и нормализует к чистому строковому значению
        ('detect', 'obb', 'segment') перед сохранением в БД.
        """
        task_value = task.value if hasattr(task, "value") else str(task).split(".")[-1].lower()

        dataset_id = self.datasets.create(
            name=name,
            task=task_value,
            owner_id=owner_id,
            description=description,
            is_private=is_private,
        )

        classes = initial_classes or _DEFAULT_CLASSES
        self.classes.ensure_classes(dataset_id=dataset_id, names=classes)

        return dataset_id

    def list_user_datasets(self, user_id: int) -> list:
        """Возвращает id датасетов, к которым у пользователя есть доступ."""
        return self.memberships.list_datasets_for_user(user_id=user_id)
