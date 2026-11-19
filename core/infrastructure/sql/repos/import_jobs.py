import logging

from core.infrastructure.sql.schema import import_jobs_table


logger = logging.getLogger(__name__)


class ImportJobRepository:
    def __init__(self,
                 db_conn):
        self.db = db_conn

    def create(self,
               user_id: int,
               dataset_id: int | None = None):
        result = self.db.execute(
            import_jobs_table.insert().values(
                user_id=user_id,
                dataset_id=dataset_id,
                status="queued",
                stage="queued",
                progress=0,
            )
        )
        self.db.commit()
        return self.get_by_id(result.inserted_primary_key[0])

    def get_by_id(self,
                  import_id: int):
        query = import_jobs_table.select().where(import_jobs_table.c.id == import_id)
        return self.db.execute(query).fetchone()

    def update_progress(self,
                        import_id: int,
                        *,
                        stage: str,
                        progress: int,
                        total_samples: int,
                        processed_samples: int,
                        imported_samples: int,
                        parse_errors: int,
                        status: str = "processing",
                        dataset_id: int | None = None) -> None:
        values = {
            "stage": stage,
            "progress": max(0, min(100, progress)),
            "total_samples": total_samples,
            "processed_samples": processed_samples,
            "imported_samples": imported_samples,
            "parse_errors": parse_errors,
            "status": status,
        }
        if dataset_id is not None:
            values["dataset_id"] = dataset_id
        self.db.execute(
            import_jobs_table.update()
            .where(import_jobs_table.c.id == import_id)
            .values(**values)
        )
        self.db.commit()

    def mark_failed(self,
                    import_id: int,
                    error: str) -> None:
        self.db.execute(
            import_jobs_table.update()
            .where(import_jobs_table.c.id == import_id)
            .values(status="failed", stage="failed", error=error)
        )
        self.db.commit()

