# core/infrastructure/sql/repos/samples.py
from datetime import datetime
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
        status: str = "unlabeled",
    ):
        """Создаёт запись сэмпла и возвращает её из БД."""
        query = samples_table.insert().values(
            dataset_id=dataset_id,
            stem=stem,
            split=split,
            image_key=image_key,
            label_key=label_key,
            thumb_key=thumb_key,
            is_labeled=is_labeled,
            parse_error=parse_error,
            status=status,
        )
        result = self.db.execute(query)
        self.db.commit()
        sample_id = result.inserted_primary_key[0]
        return self.get_by_id(dataset_id, sample_id)

    def get_by_id(self, dataset_id: int, sample_id: int):
        """Возвращает сэмпл по id, или None если не найден."""
        query = samples_table.select().where(
            (samples_table.c.id == sample_id)
            & (samples_table.c.dataset_id == dataset_id)
        )
        return self.db.execute(query).fetchone()

    def mark_updated(
        self,
        sample_id: int,
        is_labeled: bool,
        parse_error: str | None,
    ) -> None:
        """Обновляет флаг разметки и ошибку парсинга сэмпла."""
        query = (
            samples_table.update()
            .where(samples_table.c.id == sample_id)
            .values(is_labeled=is_labeled, parse_error=parse_error)
        )
        self.db.execute(query)
        self.db.commit()

    def lock_sample(
        self,
        sample_id: int,
        user_id: int,
        lock_until: datetime,
    ) -> None:
        """Блокирует сэмпл для разметки пользователем."""
        query = (
            samples_table.update()
            .where(samples_table.c.id == sample_id)
            .values(lock_user=user_id, lock_until=lock_until)
        )
        self.db.execute(query)
        self.db.commit()

    def set_status(self, sample_id: int, status: str) -> None:
        """Обновляет статус сэмпла (unlabeled, in_progress, accepted, etc.)."""
        query = (
            samples_table.update()
            .where(samples_table.c.id == sample_id)
            .values(status=status)
        )
        self.db.execute(query)
        self.db.commit()

    def list_by_status(self, dataset_id: int, status: str) -> list:
        """Возвращает все сэмплы датасета с заданным статусом."""
        query = samples_table.select().where(
            (samples_table.c.dataset_id == dataset_id)
            & (samples_table.c.status == status)
        )
        return self.db.execute(query).fetchall()

    def paginate(
        self,
        dataset_id: int,
        split: str | None,
        status: str | None,
        offset: int,
        limit: int,
    ) -> tuple[int, list]:
        """
        Возвращает (total, rows) с опциональной фильтрацией по split и статусу.
        Пагинация выполняется в Python (подходит для MVP; для продакшна — COUNT + OFFSET в SQL).
        """
        query = samples_table.select().where(samples_table.c.dataset_id == dataset_id)
        if split:
            query = query.where(samples_table.c.split == split)
        if status:
            query = query.where(samples_table.c.status == status)

        all_rows = self.db.execute(query).fetchall()
        return len(all_rows), all_rows[offset : offset + limit]

    def list_by_stem(self, dataset_id: int, split: str, stem: str) -> list:
        """Возвращает сэмплы с указанным именем файла в сплите датасета."""
        query = samples_table.select().where(
            (samples_table.c.dataset_id == dataset_id)
            & (samples_table.c.split == split)
            & (samples_table.c.stem == stem)
        )
        return self.db.execute(query).fetchall()

    def list_for_split(self, dataset_id: int, split: str) -> list:
        """Возвращает сэмплы датасета в выбранном сплите."""
        query = samples_table.select().where(
            (samples_table.c.dataset_id == dataset_id)
            & (samples_table.c.split == split)
        )
        return self.db.execute(query).fetchall()

    def delete(self, sample_id: int) -> None:
        """Удаляет сэмпл из БД."""
        query = samples_table.delete().where(samples_table.c.id == sample_id)
        self.db.execute(query)
        self.db.commit()
