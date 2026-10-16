from core.infrastructure.sql.schema import classes_table

class ClassRepository:
    def __init__(self, db_conn):
        self.db = db_conn

    def ensure_classes(self, dataset_id: int, names: list[str]) -> None:
        # Удаляем старые классы датасета
        self.db.execute(classes_table.delete().where(classes_table.c.dataset_id == dataset_id))
        
        # Вставляем новые, передавая class_index вместо id
        for idx, name in enumerate(names):
            self.db.execute(
                classes_table.insert().values(
                    dataset_id=dataset_id,
                    class_index=idx,  # <--- Исправлено с id на class_index
                    name=name
                )
            )
        self.db.commit()

    def get_names(self, dataset_id: int) -> list[str]:
        query = classes_table.select().where(classes_table.c.dataset_id == dataset_id)
        rows = self.db.execute(query).fetchall()
        return [row.name for row in rows]