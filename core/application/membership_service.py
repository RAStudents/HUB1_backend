from typing import Any, Literal

from sqlalchemy.exc import IntegrityError


MemberRole = Literal["labeler", "observer"]
_ROLE_LABELS = {
    "labeler": "разметчика",
    "observer": "наблюдателя",
}


class MembershipService:
    def __init__(self, membership_repo: Any, notification_repo: Any):
        self.memberships = membership_repo
        self.notifications = notification_repo

    def list_members(self, dataset_id: int) -> list[dict]:
        return self.memberships.list_members(dataset_id=dataset_id)

    def add_member(
        self,
        dataset_id: int,
        email: str,
        role: MemberRole,
        dataset_name: str,
        inviter_user_id: int,
    ) -> dict:
        self._validate_assignable_role(role)
        user = self.memberships.get_user_by_email(email=email)
        if user is None:
            raise LookupError(
                "Пользователь с таким email не найден. Он должен сначала "
                "зарегистрироваться."
            )

        if self.memberships.get_user_role(
            dataset_id=dataset_id,
            user_id=user.id,
        ) is not None:
            raise ValueError("Пользователь уже состоит в этом датасете")

        inviter = self.memberships.get_user_by_id(user_id=inviter_user_id)
        if inviter is None:
            raise LookupError("Владелец датасета не найден")

        notification_id = None
        try:
            self.memberships.add_member(
                dataset_id=dataset_id,
                user_id=user.id,
                role=role,
                commit=False,
            )
            notification_id = self.notifications.create(
                user_id=user.id,
                notification_type="dataset_invitation",
                title=f"Приглашение в датасет «{dataset_name}»",
                message=(
                    f"{inviter.name} добавил(а) вас в датасет "
                    f"«{dataset_name}» в роли {_ROLE_LABELS[role]}."
                ),
                dataset_id=dataset_id,
                commit=False,
            )
            self.memberships.commit()
        except IntegrityError:
            self.memberships.rollback()
            if self.memberships.get_user_role(
                dataset_id=dataset_id,
                user_id=user.id,
            ) is not None:
                raise ValueError("Пользователь уже состоит в этом датасете") from None
            raise

        member = self._get_member(dataset_id, user.id)
        member["notification_id"] = notification_id
        member["inviter_name"] = inviter.name
        return member

    def update_member_role(
        self,
        dataset_id: int,
        user_id: int,
        role: MemberRole,
    ) -> dict:
        self._validate_assignable_role(role)
        current_role = self.memberships.get_user_role(
            dataset_id=dataset_id,
            user_id=user_id,
        )
        if current_role is None:
            raise LookupError("Участник датасета не найден")
        if current_role == "owner":
            raise ValueError("Нельзя изменить роль владельца датасета")

        self.memberships.set_member_role(
            dataset_id=dataset_id,
            user_id=user_id,
            role=role,
        )
        return self._get_member(dataset_id, user_id)

    def remove_member(self, dataset_id: int, user_id: int) -> None:
        current_role = self.memberships.get_user_role(
            dataset_id=dataset_id,
            user_id=user_id,
        )
        if current_role is None:
            raise LookupError("Участник датасета не найден")
        if current_role == "owner":
            raise ValueError("Нельзя удалить владельца датасета")
        self.memberships.remove_member(dataset_id=dataset_id, user_id=user_id)

    def _get_member(self, dataset_id: int, user_id: int) -> dict:
        for member in self.memberships.list_members(dataset_id=dataset_id):
            if member["user_id"] == user_id:
                return member
        raise LookupError("Участник датасета не найден")

    @staticmethod
    def _validate_assignable_role(role: str) -> None:
        if role not in {"labeler", "observer"}:
            raise ValueError("Можно назначить только роль разметчика или наблюдателя")
