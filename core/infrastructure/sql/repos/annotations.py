from core.infrastructure.sql.schema import annotations_table


class AnnotationRepository:
    def __init__(self, db_conn):
        self.db = db_conn

    def replace_sample_annotations(
        self, sample_id: int, class_ids: list[int], user_id: int
    ) -> None:
        """Удаляет старые аннотации кадра и записывает актуальные из редактора."""
        # 1. Удаляем предыдущие записи для этого сэмпла
        self.db.execute(
            annotations_table.delete().where(
                annotations_table.c.sample_id == sample_id
            )
        )

        # 2. Вставляем новые инстансы с указанием автора
        for class_id in class_ids:
            self.db.execute(
                annotations_table.insert().values(
                    sample_id=sample_id,
                    class_id=class_id,
                    created_by=user_id,
                    updated_by=user_id,
                )
            )
        self.db.commit()