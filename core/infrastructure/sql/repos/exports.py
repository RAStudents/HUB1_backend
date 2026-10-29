# core/infrastructure/sql/repos/exports.py
from core.infrastructure.sql.schema import exports_table


class ExportRepository:
    def __init__(self, db_conn):
        self.db = db_conn

    def create_export(self, dataset_id: int, user_id: int):
        """Создаёт запись об экспорте со статусом processing."""
        query = exports_table.insert().values(
            dataset_id=dataset_id,
            user_id=user_id,
            status="processing",
            exported_samples=0,
        )
        result = self.db.execute(query)
        self.db.commit()
        export_id = result.inserted_primary_key[0]
        return self.get_by_id(dataset_id=dataset_id, export_id=export_id)

    def get_by_id(self, dataset_id: int, export_id: int):
        """Возвращает запись об экспорте по id."""
        query = exports_table.select().where(
            (exports_table.c.id == export_id)
            & (exports_table.c.dataset_id == dataset_id)
        )
        return self.db.execute(query).fetchone()

    def mark_completed(self, export_id: int, s3_key: str, exported_samples: int = 0) -> None:
        """Помечает экспорт успешно завершённым."""
        query = (
            exports_table.update()
            .where(exports_table.c.id == export_id)
            .values(status="completed", s3_key=s3_key, exported_samples=exported_samples)
        )
        self.db.execute(query)
        self.db.commit()

    def mark_failed(self, export_id: int, error: str) -> None:
        """Помечает экспорт ошибкой."""
        query = (
            exports_table.update()
            .where(exports_table.c.id == export_id)
            .values(status="failed", error=error)
        )
        self.db.execute(query)
        self.db.commit()
