# core/infrastructure/sql/repos/samples.py

import logging
from datetime import datetime
import json

from sqlalchemy import and_, func, or_, select

from core.infrastructure.sql.schema import (
    annotations_table,
    sample_geometries_table,
    samples_table,
)


logger = logging.getLogger(__name__)


class SampleRepository:
    def __init__(self, db_conn):
        self.db = db_conn

    def create_sample(self,
                      dataset_id: int,
                      stem: str,
                      split: str,
                      image_key: str,
                      label_key: str,
                      thumb_key: str,
                      is_labeled: bool = False,
                      parse_error: str | None = None,
                      status: str = "unlabeled"):
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

    def get_by_id(self,
                  dataset_id: int,
                  sample_id: int):
        """Возвращает сэмпл по id, или None если не найден."""
        query = samples_table.select().where(
            (samples_table.c.id == sample_id)
            & (samples_table.c.dataset_id == dataset_id)
        )
        return self.db.execute(query).fetchone()

    def mark_updated(self,
                     sample_id: int,
                     is_labeled: bool,
                     parse_error: str | None) -> None:
        """Обновляет флаг разметки и ошибку парсинга сэмпла."""
        query = (
            samples_table.update()
            .where(samples_table.c.id == sample_id)
            .values(is_labeled=is_labeled, parse_error=parse_error)
        )
        self.db.execute(query)
        self.db.commit()

    def lock_sample(self,
                    sample_id: int,
                    user_id: int,
                    lock_until: datetime) -> None:
        """Блокирует сэмпл для разметки пользователем."""
        query = (
            samples_table.update()
            .where(samples_table.c.id == sample_id)
            .values(lock_user=user_id, lock_until=lock_until)
        )
        self.db.execute(query)
        self.db.commit()

    def set_status(self,
                   sample_id: int,
                   status: str) -> None:
        """Обновляет статус сэмпла (unlabeled, in_progress, accepted, etc.)."""
        query = (
            samples_table.update()
            .where(samples_table.c.id == sample_id)
            .values(status=status)
        )
        self.db.execute(query)
        self.db.commit()

    def list_by_status(self,
                       dataset_id: int,
                       status: str) -> list:
        """Возвращает все сэмплы датасета с заданным статусом."""
        query = samples_table.select().where(
            (samples_table.c.dataset_id == dataset_id)
            & (samples_table.c.status == status)
        )
        return self.db.execute(query).fetchall()

    def paginate(self,
                 dataset_id: int,
                 split: str | None,
                 status: str | None,
                 offset: int,
                 limit: int) -> tuple[int, list]:
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

    def paginate_gallery(
        self,
        dataset_id: int,
        split: str | None,
        status: str | None,
        labeled: bool | None,
        search: str | None,
        object_count: str | None,
        class_ids: list[int],
        offset: int,
        limit: int,
    ) -> tuple[int, list]:
        annotation_counts = (
            select(
                annotations_table.c.sample_id,
                func.count(annotations_table.c.id).label("objects_count"),
            )
            .select_from(
                annotations_table.join(
                    samples_table,
                    annotations_table.c.sample_id == samples_table.c.id,
                )
            )
            .where(samples_table.c.dataset_id == dataset_id)
            .group_by(annotations_table.c.sample_id)
            .subquery()
        )
        filters = [samples_table.c.dataset_id == dataset_id]
        if split:
            filters.append(samples_table.c.split == split)
        if status:
            filters.append(samples_table.c.status == status)
        if labeled is not None:
            filters.append(samples_table.c.is_labeled == labeled)
        if search:
            search_term = f"%{search}%"
            filters.append(or_(
                samples_table.c.stem.ilike(search_term),
                samples_table.c.image_key.ilike(search_term),
            ))
        if class_ids:
            matching_classes = (
                select(annotations_table.c.sample_id)
                .select_from(
                    annotations_table.join(
                        samples_table,
                        annotations_table.c.sample_id == samples_table.c.id,
                    )
                )
                .where(
                    samples_table.c.dataset_id == dataset_id,
                    annotations_table.c.class_id.in_(class_ids),
                )
            )
            filters.append(samples_table.c.id.in_(matching_classes))

        object_count_expression = func.coalesce(annotation_counts.c.objects_count, 0)
        if object_count == "none":
            filters.append(object_count_expression == 0)
        elif object_count == "one":
            filters.append(object_count_expression == 1)
        elif object_count == "multiple":
            filters.append(object_count_expression > 1)

        where_clause = and_(*filters)
        total = self.db.execute(
            select(func.count(samples_table.c.id))
            .select_from(samples_table.outerjoin(
                annotation_counts,
                samples_table.c.id == annotation_counts.c.sample_id,
            ))
            .where(where_clause)
        ).scalar_one()

        query = (
            select(
                samples_table,
                object_count_expression.label("objects_count"),
                sample_geometries_table.c.geometry_json,
            )
            .select_from(
                samples_table
                .outerjoin(annotation_counts, samples_table.c.id == annotation_counts.c.sample_id)
                .outerjoin(sample_geometries_table, samples_table.c.id == sample_geometries_table.c.sample_id)
            )
            .where(where_clause)
            .order_by(samples_table.c.id)
            .offset(offset)
            .limit(limit)
        )
        rows = self.db.execute(query).fetchall()
        return total, rows

    def get_gallery_stats(self, dataset_id: int, split: str | None = None) -> dict:
        filters = [samples_table.c.dataset_id == dataset_id]
        if split:
            filters.append(samples_table.c.split == split)
        rows = self.db.execute(
            select(
                samples_table.c.is_labeled,
                func.count(samples_table.c.id),
            )
            .where(and_(*filters))
            .group_by(samples_table.c.is_labeled)
        ).fetchall()
        return {
            "labeled": sum(count for is_labeled, count in rows if is_labeled),
            "unlabeled": sum(count for is_labeled, count in rows if not is_labeled),
        }

    def get_class_counts(self, dataset_id: int) -> dict[int, int]:
        rows = self.db.execute(
            select(
                annotations_table.c.class_id,
                func.count(annotations_table.c.id),
            )
            .select_from(
                annotations_table.join(
                    samples_table,
                    annotations_table.c.sample_id == samples_table.c.id,
                )
            )
            .where(samples_table.c.dataset_id == dataset_id)
            .group_by(annotations_table.c.class_id)
        ).fetchall()
        return {class_id: count for class_id, count in rows}

    def set_geometries(
        self,
        sample_id: int,
        geometries: list[dict],
        commit: bool = True,
    ) -> None:
        geometry_json = json.dumps(geometries)
        exists = self.db.execute(
            select(sample_geometries_table.c.sample_id).where(
                sample_geometries_table.c.sample_id == sample_id
            )
        ).first()
        if exists:
            self.db.execute(
                sample_geometries_table.update()
                .where(sample_geometries_table.c.sample_id == sample_id)
                .values(geometry_json=geometry_json)
            )
        else:
            self.db.execute(
                sample_geometries_table.insert().values(
                    sample_id=sample_id,
                    geometry_json=geometry_json,
                )
            )
        if commit:
            self.db.commit()

    def commit(self) -> None:
        self.db.commit()

    def get_geometries(self, geometry_json: str | None) -> list[dict]:
        return json.loads(geometry_json) if geometry_json else []

    def list_missing_geometries(self, dataset_id: int) -> list:
        return self.db.execute(
            select(samples_table)
            .select_from(
                samples_table.outerjoin(
                    sample_geometries_table,
                    samples_table.c.id == sample_geometries_table.c.sample_id,
                )
            )
            .where(
                samples_table.c.dataset_id == dataset_id,
                sample_geometries_table.c.sample_id.is_(None),
            )
            .order_by(samples_table.c.id)
        ).fetchall()

    def list_by_stem(self, dataset_id: int, split: str, stem: str) -> list:
        """Возвращает сэмплы с указанным именем файла в сплите датасета."""
        query = samples_table.select().where(
            (samples_table.c.dataset_id == dataset_id)
            & (samples_table.c.split == split)
            & (samples_table.c.stem == stem)
        )
        return self.db.execute(query).fetchall()

    def list_for_split(self,
                       dataset_id: int,
                       split: str) -> list:
        """Возвращает сэмплы датасета в выбранном сплите."""
        query = samples_table.select().where(
            (samples_table.c.dataset_id == dataset_id)
            & (samples_table.c.split == split)
        )
        return self.db.execute(query).fetchall()

    def list_by_stems(self, dataset_id: int, split: str, stems: list[str]) -> list:
        """Возвращает сэмплы выбранного сплита с указанными именами."""
        if not stems:
            return []

        query = samples_table.select().where(
            (samples_table.c.dataset_id == dataset_id)
            & (samples_table.c.split == split)
            & samples_table.c.stem.in_(stems)
        )
        return self.db.execute(query).fetchall()

    def delete(self, sample_id: int) -> None:
        """Удаляет сэмпл из БД."""
        self.db.execute(
            annotations_table.delete().where(annotations_table.c.sample_id == sample_id)
        )
        self.db.execute(
            sample_geometries_table.delete().where(
                sample_geometries_table.c.sample_id == sample_id
            )
        )
        query = samples_table.delete().where(samples_table.c.id == sample_id)
        self.db.execute(query)
        self.db.commit()
