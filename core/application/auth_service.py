# core/application/auth_service.py
from typing import Any

from core.infrastructure.auth.passwords import hash_password, verify_password
from core.infrastructure.auth.tokens import create_access_token

_YANDEX_OAUTH_MARKER = "oauth_yandex"


def _build_token_response(user_id: int, email: str, name: str) -> dict:
    """Собирает стандартный ответ с JWT-токеном."""
    return {
        "access_token": create_access_token(user_id=user_id),
        "token_type": "bearer",
        "user_id": user_id,
        "email": email,
        "name": name,
    }


class AuthService:
    def __init__(self, user_repo: Any):
        self.users = user_repo

    def register(self, email: str, password: str, name: str) -> dict:
        """Регистрирует нового пользователя по email и паролю."""
        if self.users.get_by_email(email):
            raise ValueError("Пользователь с таким email уже существует")

        pw_hash = hash_password(password)
        user_id = self.users.create(email=email, password_hash=pw_hash, name=name)
        return _build_token_response(user_id=user_id, email=email, name=name)

    def authenticate(self, email: str, password: str) -> dict:
        """Вход по email и паролю."""
        user = self.users.get_by_email(email)
        if not user:
            raise PermissionError("Неверный email или пароль")

        if not user.password_hash or user.password_hash == _YANDEX_OAUTH_MARKER:
            raise PermissionError(
                "Этот аккаунт создан через Яндекс. Войдите через Яндекс ID."
            )

        if not verify_password(password, user.password_hash):
            raise PermissionError("Неверный email или пароль")

        return _build_token_response(user_id=user.id, email=user.email, name=user.name)

    def get_profile(self, user_id: int) -> dict:
        """Возвращает публичный профиль пользователя."""
        user = self.users.get_by_id(user_id)
        if not user:
            raise ValueError("Пользователь не найден")
        return {"user_id": user.id, "email": user.email, "name": user.name}

    def update_profile(self, user_id: int, name: str) -> dict:
        """Обновляет отображаемое имя пользователя."""
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Имя не может быть пустым")
        self.users.update_name(user_id=user_id, name=clean_name)
        return self.get_profile(user_id)

    def login_with_yandex(self, yandex_id: str, email: str, name: str) -> dict:
        """
        Вход через Яндекс OAuth без создания дублирующих аккаунтов.
        Порядок поиска: по yandex_id → по email → создание нового пользователя.
        """
        user = self.users.get_by_yandex_id(yandex_id)

        if user:
            return _build_token_response(
                user_id=user.id, email=user.email, name=user.name
            )

        existing_by_email = self.users.get_by_email(email)
        if existing_by_email:
            self.users.set_yandex_id(user_id=existing_by_email.id, yandex_id=yandex_id)
            return _build_token_response(
                user_id=existing_by_email.id,
                email=existing_by_email.email,
                name=existing_by_email.name,
            )

        new_user_id = self.users.create(
            email=email,
            password_hash=_YANDEX_OAUTH_MARKER,
            name=name,
            yandex_id=yandex_id,
        )
        return _build_token_response(user_id=new_user_id, email=email, name=name)
