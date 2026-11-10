# core/infrastructure/sql/repos/auth_tokens.py

import logging
from datetime import datetime, timezone

from sqlalchemy import delete, select

from core.infrastructure.sql.schema import (
    refresh_tokens_table,
    revoked_access_tokens_table,
)


logger = logging.getLogger(__name__)


def _aware(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class AuthTokenRepository:
    def __init__(self, db_conn):
        self.db = db_conn

    def store_refresh(
        self,
        user_id: int,
        token_hash: str,
        family_id: str,
        expires_at: datetime,
    ) -> int:
        result = self.db.execute(
            refresh_tokens_table.insert().values(
                user_id=user_id,
                token_hash=token_hash,
                family_id=family_id,
                expires_at=expires_at,
            )
        )
        self.db.commit()
        return result.inserted_primary_key[0]

    def get_refresh_by_hash(self, token_hash: str):
        query = refresh_tokens_table.select().where(
            refresh_tokens_table.c.token_hash == token_hash
        )
        return self.db.execute(query).fetchone()

    def revoke_refresh(self, token_id: int, replaced_by_id: int | None = None) -> None:
        self.db.execute(
            refresh_tokens_table.update()
            .where(refresh_tokens_table.c.id == token_id)
            .values(revoked_at=datetime.now(timezone.utc), replaced_by_id=replaced_by_id)
        )
        self.db.commit()

    def revoke_family(self, family_id: str) -> None:
        now = datetime.now(timezone.utc)
        self.db.execute(
            refresh_tokens_table.update()
            .where(
                (refresh_tokens_table.c.family_id == family_id)
                & refresh_tokens_table.c.revoked_at.is_(None)
            )
            .values(revoked_at=now)
        )
        self.db.commit()

    def revoke_all_refresh_for_user(self, user_id: int) -> None:
        now = datetime.now(timezone.utc)
        self.db.execute(
            refresh_tokens_table.update()
            .where(
                (refresh_tokens_table.c.user_id == user_id)
                & refresh_tokens_table.c.revoked_at.is_(None)
            )
            .values(revoked_at=now)
        )
        self.db.commit()

    def is_access_revoked(self, jti: str) -> bool:
        row = self.db.execute(
            select(revoked_access_tokens_table.c.expires_at).where(
                revoked_access_tokens_table.c.jti == jti
            )
        ).fetchone()
        if row is None:
            return False

        expires_at = _aware(row.expires_at)
        if expires_at is not None and expires_at <= datetime.now(timezone.utc):
            self.db.execute(
                delete(revoked_access_tokens_table).where(
                    revoked_access_tokens_table.c.jti == jti
                )
            )
            self.db.commit()
            return False
        return True

    def revoke_access(self, jti: str, user_id: int, expires_at: datetime) -> None:
        existing = self.db.execute(
            select(revoked_access_tokens_table.c.jti).where(
                revoked_access_tokens_table.c.jti == jti
            )
        ).fetchone()
        if existing is None:
            self.db.execute(
                revoked_access_tokens_table.insert().values(
                    jti=jti,
                    user_id=user_id,
                    expires_at=expires_at,
                )
            )
        self.db.execute(
            delete(revoked_access_tokens_table).where(
                revoked_access_tokens_table.c.expires_at <= datetime.now(timezone.utc)
            )
        )
        self.db.commit()