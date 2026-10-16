from typing import Any, List
from acmenra_cv import TaskType
from core.domain.enums import TaskTypeEnum


class DatasetService:
    def __init__(self, dataset_repo: Any, class_repo: Any, membership_repo: Any):
        self.datasets = dataset_repo
        self.classes = class_repo
        self.memberships = membership_repo

    def create_dataset(
        self,
        name: str,
        task: Any,  # Изменяем аннотацию типа на Any или принимаем строку
        owner_id: int,
        description: str | None = None,
        is_private: bool = True,
        initial_classes: List[str] | None = None,
    ) -> int:
        """Создает датасет, привязывает владельца и сохраняет дефолтный список классов."""
        
        # Безопасно преобразуем task в чистую строку значения ('detect', 'obb', 'segment')
        if hasattr(task, "value"):
            task_value = task.value
        else:
            task_str = str(task)
            task_value = task_str.split(".")[-1].lower()

        dataset_id = self.datasets.create(
            name=name,
            task=task_value,  # Передаем чистую строку в репозиторий
            owner_id=owner_id,
            description=description,
            is_private=is_private,
        )

        # Сохраняем классы (если переданы, иначе дефолтные)
        classes = initial_classes or ["object_a", "object_b"]
        self.classes.ensure_classes(dataset_id=dataset_id, names=classes)

        return dataset_id

    def list_user_datasets(self, user_id: int) -> list:
        """Возвращает датасеты, к которым у пользователя есть доступ (мои и доступные)."""
        return self.memberships.list_datasets_for_user(user_id=user_id)