# core/infrastructure/sql/repos/datasets.py
from sqlalchemy import select

from core.infrastructure.sql.schema import (
    annotations_table,
    classes_table,
    datasets_table,
    events_table,
    exports_table,
    memberships_table,
    samples_table,
)


class DatasetRepository:
    def __init__(self, db_conn):
        self.db = db_conn

    def create(
        self,
        name: str,
        task: str,
        owner_id: int,
        description: str | None = None,
        is_private: bool = True,
    ) -> int:
        dataset_query = datasets_table.insert().values(
            name=name,
            task=str(task),
            description=description,
            is_private=is_private,
            owner_id=owner_id,
        )
        result = self.db.execute(dataset_query)
        dataset_id = result.inserted_primary_key[0]

        membership_query = memberships_table.insert().values(
            dataset_id=dataset_id,
            user_id=owner_id,
            role="owner",
        )
        self.db.execute(membership_query)
        self.db.commit()
        return dataset_id

    def get_by_id(self, dataset_id: int):
        query = datasets_table.select().where(datasets_table.c.id == dataset_id)
        return self.db.execute(query).fetchone()

    def delete(self, dataset_id: int) -> None:
        sample_ids = select(samples_table.c.id).where(
            samples_table.c.dataset_id == dataset_id
        )
        self.db.execute(
            annotations_table.delete().where(
                annotations_table.c.sample_id.in_(sample_ids)
            )
        )
        self.db.execute(
            events_table.delete().where(events_table.c.dataset_id == dataset_id)
        )
        self.db.execute(
            samples_table.delete().where(samples_table.c.dataset_id == dataset_id)
        )
        self.db.execute(
            classes_table.delete().where(classes_table.c.dataset_id == dataset_id)
        )
        self.db.execute(
            memberships_table.delete().where(memberships_table.c.dataset_id == dataset_id)
        )
        self.db.execute(
            exports_table.delete().where(exports_table.c.dataset_id == dataset_id)
        )
        self.db.execute(datasets_table.delete().where(datasets_table.c.id == dataset_id))
        self.db.commit()

    def list_by_ids(self, dataset_ids: list[int]) -> list:
        """Возвращает список датасетов по их ID для каталога."""
        if not dataset_ids:
            return []
        query = (
            datasets_table.select()
            .where(datasets_table.c.id.in_(dataset_ids))
            .order_by(datasets_table.c.id.desc())
        )
        return self.db.execute(query).fetchall()