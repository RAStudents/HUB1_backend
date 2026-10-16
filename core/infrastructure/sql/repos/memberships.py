from core.infrastructure.sql.schema import memberships_table

class MembershipRepository:
    def __init__(self, db_conn):
        self.db = db_conn

    def get_user_role(self, dataset_id: int, user_id: int) -> str | None:
        query = memberships_table.select().where(
            (memberships_table.c.dataset_id == dataset_id) & 
            (memberships_table.c.user_id == user_id)
        )
        row = self.db.execute(query).fetchone()
        return row.role if row else None

    def list_datasets_for_user(self, user_id: int) -> list:
        query = memberships_table.select().where(memberships_table.c.user_id == user_id)
        rows = self.db.execute(query).fetchall()
        return [row.dataset_id for row in rows]