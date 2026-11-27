from datetime import datetime, timezone

from sqlalchemy import func, select

from core.infrastructure.sql.schema import (
    datasets_table, events_table, sample_comments_table, sample_geometries_table,
    samples_table, users_table,
)


class ReviewRepository:
    def __init__(self, db_conn):
        self.db = db_conn

    def transition(self, dataset_id, sample_id, user_id, expected, target, action, comment=None):
        """Commit the decision, optional comment and audit event together."""
        try:
            values = dict(status=target)
            if target in {"in_review", "accepted", "rejected"}:
                values.update(lock_user=None, lock_until=None)
            result = self.db.execute(
                samples_table.update().where(
                    samples_table.c.dataset_id == dataset_id,
                    samples_table.c.id == sample_id,
                    samples_table.c.status == expected,
                ).values(**values)
            )
            if result.rowcount != 1:
                self.db.rollback()
                return False
            if comment:
                self.db.execute(sample_comments_table.insert().values(
                    dataset_id=dataset_id, sample_id=sample_id,
                    user_id=user_id, body=comment,
                ))
            self.db.execute(events_table.insert().values(
                dataset_id=dataset_id, sample_id=sample_id, user_id=user_id,
                action=action, created_at=datetime.now(timezone.utc),
            ))
            self.db.commit()
            return True
        except Exception:
            self.db.rollback()
            raise

    def queue(self, dataset_id, labeler_id=None, sort="oldest", offset=0, limit=24):
        latest = select(
            events_table.c.sample_id,
            func.max(events_table.c.id).label("event_id"),
        ).where(
            events_table.c.dataset_id == dataset_id,
            events_table.c.action.in_([
                "sample_submitted_for_review", "sample_status_changed_to_in_review",
            ]),
        ).group_by(events_table.c.sample_id).subquery()
        source = (
            samples_table.outerjoin(latest, latest.c.sample_id == samples_table.c.id)
            .outerjoin(events_table, events_table.c.id == latest.c.event_id)
            .outerjoin(users_table, users_table.c.id == events_table.c.user_id)
        )
        filters = [samples_table.c.dataset_id == dataset_id, samples_table.c.status == "in_review"]
        queue_total = self.db.execute(
            select(func.count()).select_from(samples_table).where(*filters)
        ).scalar_one()
        labelers = self.db.execute(
            select(users_table.c.id, users_table.c.name, func.count().label("count"))
            .select_from(source).where(*filters, users_table.c.id.is_not(None))
            .group_by(users_table.c.id, users_table.c.name).order_by(users_table.c.name, users_table.c.id)
        ).all()
        if labeler_id is not None:
            filters.append(events_table.c.user_id == labeler_id)
        total = self.db.execute(select(func.count()).select_from(source).where(*filters)).scalar_one()
        submitted_order = events_table.c.created_at.asc() if sort == "oldest" else events_table.c.created_at.desc()
        id_order = samples_table.c.id.asc() if sort == "oldest" else samples_table.c.id.desc()
        rows = self.db.execute(
            select(
                samples_table, sample_geometries_table.c.geometry_json,
                events_table.c.created_at.label("submitted_at"),
                users_table.c.id.label("submitted_by_id"), users_table.c.name.label("submitted_by_name"),
            ).select_from(source.outerjoin(
                sample_geometries_table, sample_geometries_table.c.sample_id == samples_table.c.id,
            )).where(*filters).order_by(submitted_order.nulls_last(), id_order).offset(offset).limit(limit)
        ).all()
        return total, queue_total, labelers, rows

    def summary(self, owner_id):
        return self.db.execute(
            select(
                datasets_table.c.public_id.label("dataset_id"), datasets_table.c.name,
                func.count(samples_table.c.id).label("pending_count"),
            ).join(samples_table, samples_table.c.dataset_id == datasets_table.c.id)
            .where(datasets_table.c.owner_id == owner_id, samples_table.c.status == "in_review")
            .group_by(datasets_table.c.id, datasets_table.c.public_id, datasets_table.c.name).order_by(datasets_table.c.id)
        ).all()
