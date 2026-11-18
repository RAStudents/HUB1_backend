# core/application/dataset_service.py

import logging
from typing import Any, List

from core.config import LOCAL_API_BASE_URL
from core.infrastructure.s3.client import media_url


logger = logging.getLogger(__name__)


_DEFAULT_CLASSES = ["object_a", "object_b"]


class DatasetService:
    def __init__(self,
                 dataset_repo: Any,
                 class_repo: Any,
                 membership_repo: Any,
                 sample_repo: Any):
        self.datasets = dataset_repo
        self.classes = class_repo
        self.memberships = membership_repo
        self.samples = sample_repo

    def create_dataset(self,
                       name: str,
                       task: Any,
                       owner_id: int,
                       description: str | None = None,
                       is_private: bool = True,
                       initial_classes: List[str] | None = None) -> int:
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

    def list_user_datasets(self,
                           user_id: int,
                           base_url: str = LOCAL_API_BASE_URL) -> list[dict]: # TODO needs to rm fix link
        """Собирает каталог датасетов для главной страницы пользователя."""
        dataset_ids = self.memberships.list_datasets_for_user(user_id=user_id)
        rows = self.datasets.list_by_ids(dataset_ids)
        sample_counts = self.samples.count_by_dataset_ids(dataset_ids)
        base_url = base_url.rstrip("/")

        catalog = []
        for row in rows:
            classes = self.classes.get_names(dataset_id=row.id)
            thumb_key = self.samples.first_thumb_key(row.id)
            cover_url = media_url(thumb_key, base_url=base_url) if thumb_key else None

            catalog.append({
                "id": row.public_id,
                "name": row.name,
                "task": row.task,
                "description": row.description,
                "is_private": row.is_private,
                "classes": classes,
                "images_count": sample_counts.get(row.id, 0),
                "cover_url": cover_url,
                "is_owner": row.owner_id == user_id,
                "my_role": self.memberships.get_user_role(dataset_id=row.id, user_id=user_id),
                "created_at": str(row.created_at) if row.created_at else None,
            })

        return catalog

    def delete_dataset(self,
                       dataset_id: int) -> None:
        self.datasets.delete(dataset_id=dataset_id)