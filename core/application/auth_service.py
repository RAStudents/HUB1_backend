from typing import Any
from core.infrastructure.auth.passwords import hash_password, verify_password
from core.infrastructure.auth.tokens import create_access_token


class AuthService:
    def __init__(self, user_repo: Any):
        self.users = user_repo

    def register(self, email: str, password: str, name: str) -> dict:
        """Регистрирует нового пользователя по почте и паролю."""
        existing = self.users.get_by_email(email)
        if existing:
            raise ValueError("Пользователь с таким email уже существует")

        pw_hash = hash_password(password)
        user_id = self.users.create(email=email, password_hash=pw_hash, name=name)
        
        token = create_access_token(user_id=user_id)
        return {
            "access_token": token,
            "token_type": "bearer",
            "user_id": user_id,
            "email": email,
            "name": name,
        }

    def authenticate(self, email: str, password: str) -> dict:
        """Вход по email и паролю."""
        user = self.users.get_by_email(email)
        if not user:
            raise PermissionError("Неверный email или пароль")

        if not user.password_hash or user.password_hash == "oauth_yandex":
            raise PermissionError("Этот аккаунт создан через Яндекс. Войдите через Яндекс ID.")

        if not verify_password(password, user.password_hash):
            raise PermissionError("Неверный email или пароль")

        token = create_access_token(user_id=user.id)
        return {
            "access_token": token,
            "token_type": "bearer",
            "user_id": user.id,
            "email": user.email,
            "name": user.name,
        }

    def get_profile(self, user_id: int) -> dict:
        """Возвращает профиль пользователя (включая отображаемое имя)."""
        user = self.users.get_by_id(user_id)
        if not user:
            raise ValueError("Пользователь не найден")
        return {
            "user_id": user.id,
            "email": user.email,
            "name": user.name,
        }

    def update_profile(self, user_id: int, name: str) -> dict:
        """Обновляет отображаемое имя пользователя."""
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Имя не может быть пустым")
        self.users.update_name(user_id=user_id, name=clean_name)
        return self.get_profile(user_id)

    def login_with_yandex(self, yandex_id: str, email: str, name: str) -> dict:
        """Вход через Яндекс без создания дубликатов."""
        user = self.users.get_by_yandex_id(yandex_id)
        
        if not user:
            user = self.users.get_by_email(email)
            if user:
                self.users.set_yandex_id(user_id=user.id, yandex_id=yandex_id)
                user_id = user.id
                user_email = user.email
                user_name = user.name
            else:
                user_id = self.users.create(
                    email=email,
                    password_hash="oauth_yandex",
                    name=name,
                    yandex_id=yandex_id,
                )
                user_email = email
                user_name = name
        else:
            user_id = user.id
            user_email = user.email
            user_name = user.name

        token = create_access_token(user_id=user_id)
        return {
            "access_token": token,
            "token_type": "bearer",
            "user_id": user_id,
            "email": user_email,
            "name": user_name,
        }