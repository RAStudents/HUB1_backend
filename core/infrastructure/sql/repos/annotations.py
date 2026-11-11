# core/infrastructure/sql/repos/annotations.py

import logging
from core.infrastructure.sql.schema import annotations_table


logger = logging.getLogger(__name__)


class AnnotationRepository:
    def __init__(self, db_conn):
        self.db = db_conn

    def replace_sample_annotations(
        self,
        sample_id: int,
        class_ids: list[int],
        user_id: int | None,
        commit: bool = True,
    ) -> None:
        """
        Атомарно заменяет аннотации кадра:
        удаляет старые записи и вставляет актуальные из редактора.
        """
        self.db.execute(
            annotations_table.delete().where(
                annotations_table.c.sample_id == sample_id
            )
        )
        if class_ids:
            self.db.execute(
                annotations_table.insert(),
                [
                    {
                        "sample_id": sample_id,
                        "class_id": class_id,
                        "created_by": user_id,
                        "updated_by": user_id,
                    }
                    for class_id in class_ids
                ],
            )
        if commit:
            self.db.commit()
