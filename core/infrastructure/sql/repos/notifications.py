from sqlalchemy import func, select

from core.infrastructure.sql.schema import notifications_table


class NotificationRepository:
    def __init__(self, db_conn):
        self.db = db_conn

    def create(
        self,
        user_id: int,
        notification_type: str,
        title: str,
        message: str,
        dataset_id: int | None = None,
        commit: bool = True,
    ) -> int:
        result = self.db.execute(
            notifications_table.insert().values(
                user_id=user_id,
                type=notification_type,
                title=title,
                message=message,
                dataset_id=dataset_id,
                is_read=False,
            )
        )
        notification_id = result.inserted_primary_key[0]
        if commit:
            self.db.commit()
        return notification_id

    def list_for_user(
        self,
        user_id: int,
        offset: int,
        limit: int,
    ) -> tuple[list, int, int]:
        rows = self.db.execute(
            select(notifications_table)
            .where(notifications_table.c.user_id == user_id)
            .order_by(
                notifications_table.c.created_at.desc(),
                notifications_table.c.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        ).fetchall()
        total = self.db.execute(
            select(func.count())
            .select_from(notifications_table)
            .where(notifications_table.c.user_id == user_id)
        ).scalar_one()
        unread_count = self.get_unread_count(user_id)
        return [dict(row._mapping) for row in rows], total, unread_count

    def get_unread_count(self, user_id: int) -> int:
        return self.db.execute(
            select(func.count())
            .select_from(notifications_table)
            .where(
                notifications_table.c.user_id == user_id,
                notifications_table.c.is_read.is_(False),
            )
        ).scalar_one()

    def mark_read(self, user_id: int, notification_id: int) -> bool:
        result = self.db.execute(
            notifications_table.update()
            .where(
                notifications_table.c.id == notification_id,
                notifications_table.c.user_id == user_id,
            )
            .values(is_read=True)
        )
        self.db.commit()
        return result.rowcount > 0

    def mark_all_read(self, user_id: int) -> int:
        result = self.db.execute(
            notifications_table.update()
            .where(
                notifications_table.c.user_id == user_id,
                notifications_table.c.is_read.is_(False),
            )
            .values(is_read=True)
        )
        self.db.commit()
        return result.rowcount

    def commit(self) -> None:
        self.db.commit()

    def rollback(self) -> None:
        self.db.rollback()
