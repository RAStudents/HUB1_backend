from sqlalchemy import select

from core.infrastructure.sql.schema import visitor_data_consent_events_table


class ConsentRepository:
    def __init__(self, db_conn):
        self.db = db_conn

    def get_latest(self, visitor_id: str, version: str):
        row = self.db.execute(
            select(visitor_data_consent_events_table)
            .where(
                visitor_data_consent_events_table.c.visitor_id == visitor_id,
                visitor_data_consent_events_table.c.version == version,
            )
            .order_by(
                visitor_data_consent_events_table.c.created_at.desc(),
                visitor_data_consent_events_table.c.id.desc(),
            )
            .limit(1)
        ).fetchone()
        return dict(row._mapping) if row is not None else None

    def record(self, visitor_id: str, version: str, action: str) -> dict:
        result = self.db.execute(
            visitor_data_consent_events_table.insert().values(
                visitor_id=visitor_id,
                version=version,
                action=action,
            )
        )
        self.db.commit()
        row = self.db.execute(
            select(visitor_data_consent_events_table).where(
                visitor_data_consent_events_table.c.id == result.inserted_primary_key[0]
            )
        ).fetchone()
        return dict(row._mapping)
