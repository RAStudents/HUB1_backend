# core/infrastructure/sql/repos/samples.py

import logging
from datetime import datetime
import json

from sqlalchemy import and_, func, or_, select, text

from core.infrastructure.sql.schema import (
    annotations_table,
    sample_geometries_table,
    samples_table,
)


logger = logging.getLogger(__name__)


class SampleRepository:
    def __init__(self,
                 db_conn):
        self.db = db_conn

    def count_by_dataset_ids(self,
                             dataset_ids: list[int]) -> dict[int, int]:
        if not dataset_ids:
            return {}

        rows = self.db.execute(
            select(samples_table.c.dataset_id, func.count(samples_table.c.id))
            .where(samples_table.c.dataset_id.in_(dataset_ids))
            .group_by(samples_table.c.dataset_id)
        ).all()
        return {dataset_id: count for dataset_id, count in rows}

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

    def update_split_and_keys(self,
                              dataset_id: int,
                              sample_id: int,
                              split: str,
                              image_key: str,
                              label_key: str,
                              thumb_key: str) -> None:
        self.db.execute(
            samples_table.update()
            .where(
                samples_table.c.dataset_id == dataset_id,
                samples_table.c.id == sample_id,
            )
            .values(
                split=split,
                image_key=image_key,
                label_key=label_key,
                thumb_key=thumb_key,
            )
        )
        self.db.commit()

    def lock_sample(self,
                    sample_id: int,
                    user_id: int,
                    lock_until: datetime) -> None:
        """Блокирует сэмпл для разметки пользователем."""
        query = (
            samples_table.update()
            .where(samples_table.c.id == sample_id)
            .values(
                lock_user=user_id,
                lock_until=lock_until,
                status="in_progress",
            )
        )
        self.db.execute(query)
        self.db.commit()


    def acquire_sample_lock(self,
                            dataset_id: int,
                            sample_id: int,
                            user_id: int,
                            lock_until: datetime,
                            now: datetime,
                            allowed_statuses: set[str] | None = None) -> bool:
        result = self.db.execute(
            samples_table.update()
            .where(
                samples_table.c.dataset_id == dataset_id,
                samples_table.c.id == sample_id,
                samples_table.c.status.in_(allowed_statuses if allowed_statuses is not None else {"unlabeled", "in_progress", "rejected"}),
                or_(
                    samples_table.c.lock_user.is_(None),
                    samples_table.c.lock_until.is_(None),
                    samples_table.c.lock_until <= now,
                    samples_table.c.lock_user == user_id,
                ),
            )
            .values(
                lock_user=user_id,
                lock_until=lock_until,
                status="in_progress",
            )
        )
        if result.rowcount:
            self.db.commit()
            return True
        self.db.rollback()
        return False

    def renew_owned_lock(self, dataset_id: int, sample_id: int, user_id: int,
                         now: datetime, lock_until: datetime) -> bool:
        result = self.db.execute(
            samples_table.update().where(
                samples_table.c.dataset_id == dataset_id,
                samples_table.c.id == sample_id,
                samples_table.c.status == "in_progress",
                samples_table.c.lock_user == user_id,
                samples_table.c.lock_until > now,
            ).values(lock_until=lock_until)
        )
        self.db.commit()
        return result.rowcount == 1

    def release_sample_lock(self,
                            dataset_id: int,
                            sample_id: int,
                            user_id: int | None = None) -> bool:
        query = samples_table.update().where(
            samples_table.c.dataset_id == dataset_id,
            samples_table.c.id == sample_id,
            samples_table.c.lock_user.is_not(None),
        )
        if user_id is not None:
            query = query.where(samples_table.c.lock_user == user_id)
        result = self.db.execute(
            query.values(lock_user=None, lock_until=None)
        )
        if result.rowcount:
            self.db.commit()
            return True
        self.db.rollback()
        return False

    def unlock_sample(self,
                      sample_id: int) -> None:
        query = (
            samples_table.update()
            .where(samples_table.c.id == sample_id)
            .values(lock_user=None, lock_until=None)
        )
        self.db.execute(query)
        self.db.commit()

    def set_status_if(self,
                      sample_id: int,
                      expected: str,
                      status: str) -> bool:
        result = self.db.execute(
            samples_table.update()
            .where(
                (samples_table.c.id == sample_id)
                & (samples_table.c.status == expected)
            )
            .values(status=status)
        )
        self.db.commit()
        return result.rowcount == 1

    def first_thumb_key(self,
                        dataset_id: int) -> str | None:
        row = self.db.execute(
            select(samples_table.c.thumb_key)
            .where(samples_table.c.dataset_id == dataset_id)
            .order_by(samples_table.c.id)
            .limit(1)
        ).first()
        return row.thumb_key if row else None


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

    def list_by_status_and_class_ids(self,
                                     dataset_id: int,
                                     status: str,
                                     class_ids: list[int]) -> list:
        """Возвращает сэмплы с заданным статусом, содержащие любой из классов."""
        matching_sample_ids = (
            select(annotations_table.c.sample_id)
            .select_from(
                annotations_table.join(
                    samples_table,
                    annotations_table.c.sample_id == samples_table.c.id,
                )
            )
            .where(
                samples_table.c.dataset_id == dataset_id,
                samples_table.c.status == status,
                annotations_table.c.class_id.in_(class_ids),
            )
            .distinct()
        )
        query = samples_table.select().where(
            samples_table.c.id.in_(matching_sample_ids)
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

    def paginate_gallery(self,
                         dataset_id: int,
                         split: str | None,
                         status: str | None,
                         labeled: bool | None,
                         search: str | None,
                         object_count: str | None,
                         class_ids: list[int],
                         offset: int,
                         limit: int,
                         stems: list[str] | None = None,
                         anchor_sample_id: int | None = None) -> tuple[int, list, int]:
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
            escaped = (
                search.replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            search_term = f"%{escaped}%"
            image_key = samples_table.c.image_key
            marker = "/images/"
            marker_position = (
                func.strpos(image_key, marker)
                if self.db.get_bind().dialect.name == "postgresql"
                else func.instr(image_key, marker)
            )
            filters.append(or_(
                samples_table.c.stem.ilike(search_term, escape="\\"),
                and_(marker_position > 0,
                     func.substr(image_key, marker_position + len(marker)).ilike(search_term, escape="\\")),
            ))
        if stems:
            filters.append(samples_table.c.stem.in_(stems))
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
        count_query = (
            select(func.count(samples_table.c.id))
            .select_from(samples_table.outerjoin(
                annotation_counts,
                samples_table.c.id == annotation_counts.c.sample_id,
            ))
            .where(where_clause)
        )
        if anchor_sample_id is None:
            total = self.db.execute(count_query).scalar_one()
        else:
            total, preceding, present = self.db.execute(count_query.add_columns(
                func.count().filter(samples_table.c.id < anchor_sample_id),
                func.count().filter(samples_table.c.id == anchor_sample_id),
            )).one()
            if not present:
                raise LookupError("Кадр не найден.")
            offset = (preceding // limit) * limit

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
        return total, rows, offset

    def get_gallery_stats(self,
                          dataset_id: int,
                          split: str | None = None) -> dict:
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

    def get_class_counts(self,
                         dataset_id: int) -> dict[int, int]:
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

    def set_geometries(self,
                       sample_id: int,
                       geometries: list[dict],
                       commit: bool = True) -> None:
        self.db.execute(text("""
            INSERT INTO sample_geometries (sample_id, geometry_json)
            VALUES (:sample_id, :geometry_json)
            ON CONFLICT (sample_id) DO UPDATE SET geometry_json = excluded.geometry_json
        """), {"sample_id": sample_id, "geometry_json": json.dumps(geometries)})
        if commit:
            self.db.commit()

    def commit(self) -> None:
        self.db.commit()

    def set_missing_geometries(self, sample_id: int, geometries: list[dict]) -> None:
        self.db.execute(text("""
            INSERT INTO sample_geometries (sample_id, geometry_json)
            SELECT id, :geometry_json FROM samples WHERE id = :sample_id
            ON CONFLICT (sample_id) DO NOTHING
        """), {"sample_id": sample_id, "geometry_json": json.dumps(geometries)})

    def get_geometries(self,
                       geometry_json: str | None) -> list[dict]:
        return json.loads(geometry_json) if geometry_json else []

    def get_geometries_for_sample(self,
                                  sample_id: int) -> list[dict]:
        row = self.db.execute(
            select(sample_geometries_table.c.geometry_json).where(
                sample_geometries_table.c.sample_id == sample_id
            )
        ).first()
        return self.get_geometries(row.geometry_json if row else None)

    def list_missing_geometries(self,
                                dataset_id: int) -> list:
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

    def iter_statistics_rows(self,
                             dataset_id: int) -> list:
        return self.db.execute(
            select(
                samples_table.c.id,
                samples_table.c.split,
                samples_table.c.is_labeled,
                samples_table.c.status,
                sample_geometries_table.c.geometry_json,
            )
            .select_from(
                samples_table.outerjoin(
                    sample_geometries_table,
                    samples_table.c.id == sample_geometries_table.c.sample_id,
                )
            )
            .where(samples_table.c.dataset_id == dataset_id)
            .order_by(samples_table.c.id)
        ).fetchall()

    def list_by_stem(self,
                     dataset_id: int,
                     split: str,
                     stem: str) -> list:
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

    def list_by_stems(self,
                      dataset_id: int,
                      split: str,
                      stems: list[str]) -> list:
        """Возвращает сэмплы выбранного сплита с указанными именами."""
        if not stems:
            return []

        query = samples_table.select().where(
            (samples_table.c.dataset_id == dataset_id)
            & (samples_table.c.split == split)
            & samples_table.c.stem.in_(stems)
        )
        return self.db.execute(query).fetchall()

    def delete(self,
               sample_id: int) -> None:
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
