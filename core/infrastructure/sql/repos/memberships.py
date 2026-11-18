# core/infrastructure/sql/repos/memberships.py

import logging
from sqlalchemy import func, select

from core.infrastructure.sql.schema import (
    datasets_table,
    memberships_table,
    users_table,
)


logger = logging.getLogger(__name__)


class MembershipRepository:
    def __init__(self,
                 db_conn):
        self.db = db_conn

    def get_user_role(self,
                      dataset_id: int,
                      user_id: int) -> str | None:
        """Возвращает роль пользователя в датасете, или None если он не участник."""
        owner_query = select(datasets_table.c.owner_id).where(
            datasets_table.c.id == dataset_id
        )
        if self.db.execute(owner_query).scalar_one_or_none() == user_id:
            return "owner"

        query = select(memberships_table.c.role).where(
            (memberships_table.c.dataset_id == dataset_id)
            & (memberships_table.c.user_id == user_id)
            & (memberships_table.c.status == "accepted")
        )
        return self.db.execute(query).scalar_one_or_none()

    def list_datasets_for_user(self,
                               user_id: int) -> list[int]:
        """Возвращает список id датасетов, доступных пользователю."""
        membership_query = select(memberships_table.c.dataset_id).where(
            memberships_table.c.user_id == user_id,
            memberships_table.c.status == "accepted",
        )
        owned_query = select(datasets_table.c.id).where(
            datasets_table.c.owner_id == user_id
        )
        dataset_ids = set(self.db.execute(membership_query).scalars())
        dataset_ids.update(self.db.execute(owned_query).scalars())
        return sorted(dataset_ids)

    def list_members(self,
                     dataset_id: int) -> list[dict]:
        query = (
            select(
                memberships_table.c.user_id.label("user_id"),
                users_table.c.email,
                users_table.c.name,
                memberships_table.c.role,
                memberships_table.c.status,
            )
            .select_from(
                memberships_table.join(
                    users_table,
                    memberships_table.c.user_id == users_table.c.id,
                )
            )
            .where(memberships_table.c.dataset_id == dataset_id)
        )
        members = [
            dict(row._mapping) for row in self.db.execute(query).fetchall()
        ]

        owner_query = (
            select(
                users_table.c.id.label("user_id"),
                users_table.c.email,
                users_table.c.name,
            )
            .select_from(
                datasets_table.join(
                    users_table,
                    datasets_table.c.owner_id == users_table.c.id,
                )
            )
            .where(datasets_table.c.id == dataset_id)
        )
        owner = self.db.execute(owner_query).first()
        if owner is not None:
            owner_member = {
                **dict(owner._mapping),
                "role": "owner",
                "status": "accepted",
            }
            existing = next(
                (member for member in members if member["user_id"] == owner.user_id),
                None,
            )
            if existing is None:
                members.append(owner_member)
            else:
                existing["role"] = "owner"

        return sorted(members, key=lambda member: (member["role"] != "owner", member["email"]))

    def list_pending_invitations(self,
                                 user_id: int) -> list[dict]:
        owner = users_table.alias("owner")
        query = (
            select(
                datasets_table.c.public_id.label("dataset_id"),
                datasets_table.c.name.label("dataset_name"),
                memberships_table.c.role,
                owner.c.name.label("inviter_name"),
            )
            .select_from(
                memberships_table
                .join(
                    datasets_table,
                    datasets_table.c.id == memberships_table.c.dataset_id,
                )
                .join(owner, owner.c.id == datasets_table.c.owner_id)
            )
            .where(
                memberships_table.c.user_id == user_id,
                memberships_table.c.status == "pending",
            )
            .order_by(datasets_table.c.id.desc())
        )
        return [
            dict(row._mapping) for row in self.db.execute(query).fetchall()
        ]

    def get_user_by_email(self,
                          email: str):
        query = select(
            users_table.c.id,
            users_table.c.email,
            users_table.c.name,
        ).where(func.lower(users_table.c.email) == email.strip().lower())
        return self.db.execute(query).first()

    def get_user_by_id(self,
                       user_id: int):
        query = select(
            users_table.c.id,
            users_table.c.email,
            users_table.c.name,
        ).where(users_table.c.id == user_id)
        return self.db.execute(query).first()

    def add_member(self,
                   dataset_id: int,
                   user_id: int,
                   role: str,
                   status: str = "accepted",
                   commit: bool = True) -> None:
        self.db.execute(
            memberships_table.insert().values(
                dataset_id=dataset_id,
                user_id=user_id,
                role=role,
                status=status,
            )
        )
        if commit:
            self.db.commit()

    def get_membership_status(self,
                              dataset_id: int,
                              user_id: int) -> str | None:
        query = select(memberships_table.c.status).where(
            memberships_table.c.dataset_id == dataset_id,
            memberships_table.c.user_id == user_id,
        )
        return self.db.execute(query).scalar_one_or_none()

    def set_membership_status(self,
                              dataset_id: int,
                              user_id: int,
                              current_status: str,
                              status: str) -> bool:
        result = self.db.execute(
            memberships_table.update()
            .where(
                memberships_table.c.dataset_id == dataset_id,
                memberships_table.c.user_id == user_id,
                memberships_table.c.status == current_status,
            )
            .values(status=status)
        )
        return result.rowcount > 0

    def delete_pending_invitation(self,
                                  dataset_id: int,
                                  user_id: int) -> bool:
        result = self.db.execute(
            memberships_table.delete().where(
                memberships_table.c.dataset_id == dataset_id,
                memberships_table.c.user_id == user_id,
                memberships_table.c.status == "pending",
            )
        )
        return result.rowcount > 0

    def set_member_role(self,
                        dataset_id: int,
                        user_id: int,
                        role: str) -> bool:
        result = self.db.execute(
            memberships_table.update()
            .where(
                (memberships_table.c.dataset_id == dataset_id)
                & (memberships_table.c.user_id == user_id)
            )
            .values(role=role)
        )
        if result.rowcount:
            self.db.commit()
            return True
        return False

    def remove_member(self,
                      dataset_id: int,
                      user_id: int) -> bool:
        result = self.db.execute(
            memberships_table.delete().where(
                (memberships_table.c.dataset_id == dataset_id)
                & (memberships_table.c.user_id == user_id)
            )
        )
        if result.rowcount:
            self.db.commit()
            return True
        return False

    def rollback(self) -> None:
        self.db.rollback()

    def commit(self) -> None:
        self.db.commit()
