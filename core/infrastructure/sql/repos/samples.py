from core.domain.sample import Sample
from core.domain.enums import SplitEnum, SampleStatusEnum
from core.infrastructure.sql.schema import samples_table


class SampleRepository:
    def __init__(self, db_conn):
        self.db = db_conn

    def create_sample(
        self,
        dataset_id: int,
        stem: str,
        split: str,
        image_key: str,
        label_key: str,
        thumb_key: str,
        is_labeled: bool = False,
        parse_error: str | None = None,
    ):
        query = samples_table.insert().values(
            dataset_id=dataset_id,
            stem=stem,
            split=split,
            image_key=image_key,
            label_key=label_key,
            thumb_key=thumb_key,
            is_labeled=is_labeled,
            parse_error=parse_error,
            status="unlabeled",
        )
        result = self.db.execute(query)
        sample_id = result.inserted_primary_key[0]
        return self.get_by_id(dataset_id, sample_id)

    def get_by_id(self, dataset_id: int, sample_id: int):
        query = samples_table.select().where(
            (samples_table.c.id == sample_id) & (samples_table.c.dataset_id == dataset_id)
        )
        return self.db.execute(query).fetchone()

    def mark_updated(self, sample_id: int, is_labeled: bool, parse_error: str | None):
        query = (
            samples_table.update()
            .where(samples_table.c.id == sample_id)
            .values(is_labeled=is_labeled, parse_error=parse_error)
        )
        self.db.execute(query)

    def list_by_status(self, dataset_id: int, status: str):
        query = samples_table.select().where(
            (samples_table.c.dataset_id == dataset_id) & (samples_table.c.status == status)
        )
        return self.db.execute(query).fetchall()

    def paginate(self, dataset_id: int, split: str | None, status: str | None, offset: int, limit: int):
        query = samples_table.select().where(samples_table.c.dataset_id == dataset_id)
        if split:
            query = query.where(samples_table.c.split == split)
        if status:
            query = query.where(samples_table.c.status == status)
        
        # Получаем общее число и срез
        all_rows = self.db.execute(query).fetchall()
        total = len(all_rows)
        sliced_rows = all_rows[offset : offset + limit]
        return total, sliced_rows

    def delete(self, sample_id: int):
        query = samples_table.delete().where(samples_table.c.id == sample_id)
        self.db.execute(query)