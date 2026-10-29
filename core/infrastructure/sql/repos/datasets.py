# core/infrastructure/sql/repos/datasets.py
from core.infrastructure.sql.schema import datasets_table, memberships_table


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
        """
        Создаёт датасет и автоматически добавляет владельца
        в таблицу участников с ролью 'owner'.
        """
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
