from sqlalchemy import select

from core.infrastructure.sql.schema import sample_comments_table, users_table


class SampleCommentRepository:
    def __init__(self, db_conn):
        self.db = db_conn

    def list_for_sample(self, dataset_id: int, sample_id: int) -> list:
        query = (
            select(sample_comments_table, users_table.c.name.label("author_name"))
            .join(users_table, users_table.c.id == sample_comments_table.c.user_id)
            .where(
                sample_comments_table.c.dataset_id == dataset_id,
                sample_comments_table.c.sample_id == sample_id,
            )
            .order_by(sample_comments_table.c.created_at, sample_comments_table.c.id)
        )
        return self.db.execute(query).fetchall()

    def get_by_id(self, dataset_id: int, sample_id: int, comment_id: int):
        query = (
            select(sample_comments_table, users_table.c.name.label("author_name"))
            .join(users_table, users_table.c.id == sample_comments_table.c.user_id)
            .where(
                sample_comments_table.c.dataset_id == dataset_id,
                sample_comments_table.c.sample_id == sample_id,
                sample_comments_table.c.id == comment_id,
            )
        )
        return self.db.execute(query).first()

    def create(self, dataset_id: int, sample_id: int, user_id: int,
               body: str, parent_id: int | None = None,
               annotation_index: int | None = None):
        result = self.db.execute(
            sample_comments_table.insert().values(
                dataset_id=dataset_id,
                sample_id=sample_id,
                user_id=user_id,
                body=body,
                parent_id=parent_id,
                annotation_index=annotation_index,
            )
        )
        self.db.commit()
        return self.get_by_id(dataset_id, sample_id, result.inserted_primary_key[0])

    def set_resolved(self, comment_id: int, resolved: bool) -> None:
        self.db.execute(
            sample_comments_table.update()
            .where(sample_comments_table.c.id == comment_id)
            .values(resolved=resolved)
        )
        self.db.commit()
