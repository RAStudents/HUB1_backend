# core/infrastructure/sql/repos/events.py
from core.infrastructure.sql.schema import events_table


class EventRepository:
    def __init__(self, db_conn):
        self.db = db_conn

    def log(
        self,
        dataset_id: int,
        action: str,
        sample_id: int | None = None,
        user_id: int | None = None,
    ):
        """Записывает событие аудита в базу данных."""
        query = events_table.insert().values(
            dataset_id=dataset_id,
            sample_id=sample_id,
            user_id=user_id,
            action=action,
        )
        self.db.execute(query)
        self.db.commit()
