# core/infrastructure/sql/repos/memberships.py

import logging
from core.infrastructure.sql.schema import memberships_table


logger = logging.getLogger(__name__)


class MembershipRepository:
    def __init__(self,
                 db_conn):
        self.db = db_conn

    def get_user_role(self,
                      dataset_id: int,
                      user_id: int) -> str | None:
        """Возвращает роль пользователя в датасете, или None если он не участник."""
        query = memberships_table.select().where(
            (memberships_table.c.dataset_id == dataset_id)
            & (memberships_table.c.user_id == user_id)
        )
        row = self.db.execute(query).fetchone()
        return row.role if row else None

    def list_datasets_for_user(self,
                               user_id: int) -> list[int]:
        """Возвращает список id датасетов, доступных пользователю."""
        query = memberships_table.select().where(
            memberships_table.c.user_id == user_id
        )
        rows = self.db.execute(query).fetchall()
        return [row.dataset_id for row in rows]
