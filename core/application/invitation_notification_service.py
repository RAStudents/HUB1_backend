from typing import Any


_ROLE_LABELS = {
    "labeler": "разметчика",
    "observer": "наблюдателя",
}


class InvitationNotificationService:
    def __init__(self, email_service: Any):
        self.email = email_service

    def send_dataset_invitation(
        self,
        to_email: str,
        dataset_name: str,
        role: str,
        inviter_name: str,
    ) -> None:
        role_label = _ROLE_LABELS.get(role)
        if role_label is None:
            raise ValueError("Нельзя отправить приглашение с этой ролью")

        try:
            email_service = self.email() if callable(self.email) else self.email
            email_service.send_email(
                to_email=to_email,
                subject=f"Вас пригласили в датасет «{dataset_name}»",
                body=(
                    f"Здравствуйте!\n\n"
                    f"{inviter_name} добавил(а) вас в датасет «{dataset_name}» "
                    f"в роли {role_label}.\n\n"
                    "Войдите в HUB под этим email, чтобы открыть датасет "
                    "в разделе «Доступные мне»."
                ),
            )
        except ValueError as exc:
            raise RuntimeError("Некорректные данные для отправки email") from exc
