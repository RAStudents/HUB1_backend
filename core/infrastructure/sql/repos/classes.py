# core/infrastructure/sql/repos/classes.py

import logging
from core.infrastructure.sql.schema import classes_table


logger = logging.getLogger(__name__)


class ClassRepository:
    def __init__(self,
                 db_conn):
        self.db = db_conn

    def ensure_classes(self,
                       dataset_id: int,
                       names: list[str]) -> None:
        """
        Синхронизирует классы датасета с переданным списком:
        удаляет старые записи и вставляет актуальные.
        """
        self.db.execute(
            classes_table.delete().where(classes_table.c.dataset_id == dataset_id)
        )
        for idx, name in enumerate(names):
            self.db.execute(
                classes_table.insert().values(
                    dataset_id=dataset_id,
                    class_index=idx,
                    name=name,
                )
            )
        self.db.commit()

    def get_names(self,
                  dataset_id: int) -> list[str]:
        """Возвращает список имён классов датасета в порядке class_index."""
        query = (
            classes_table.select()
            .where(classes_table.c.dataset_id == dataset_id)
            .order_by(classes_table.c.class_index)
        )
        rows = self.db.execute(query).fetchall()
        return [row.name for row in rows]

    def list_for_dataset(self,
                         dataset_id: int) -> list:
        query = (
            classes_table.select()
            .where(classes_table.c.dataset_id == dataset_id)
            .order_by(classes_table.c.class_index)
        )
        return self.db.execute(query).fetchall()

    def add_class(self,
                  dataset_id: int,
                  name: str) -> int:
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("Название класса не может быть пустым")

        rows = self.list_for_dataset(dataset_id)
        if any(row.name.casefold() == normalized_name.casefold() for row in rows):
            raise ValueError("Класс с таким названием уже существует")

        class_index = max((row.class_index for row in rows), default=-1) + 1
        self.db.execute(
            classes_table.insert().values(
                dataset_id=dataset_id,
                class_index=class_index,
                name=normalized_name,
            )
        )
        self.db.commit()
        return class_index

    def rename_class(self,
                     dataset_id: int,
                     class_index: int,
                     name: str) -> str:
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError("Название класса не может быть пустым")

        rows = self.list_for_dataset(dataset_id)
        current = next((row for row in rows if row.class_index == class_index), None)
        if current is None:
            raise LookupError("Класс не найден")
        if any(
            row.class_index != class_index
            and row.name.casefold() == normalized_name.casefold()
            for row in rows
        ):
            raise ValueError("Класс с таким названием уже существует")

        self.db.execute(
            classes_table.update()
            .where(
                classes_table.c.dataset_id == dataset_id,
                classes_table.c.class_index == class_index,
            )
            .values(name=normalized_name)
        )
        self.db.commit()
        return normalized_name
