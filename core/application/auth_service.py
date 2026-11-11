# core/application/auth_service.py

import logging
from datetime import datetime, timezone
from typing import Any

from core.infrastructure.auth.passwords import hash_password, needs_rehash, verify_password
from core.infrastructure.auth.tokens import (
    access_ttl,
    create_access_token,
    hash_refresh_token,
    new_family_id,
    new_refresh_token,
    refresh_ttl,
)


logger = logging.getLogger(__name__)


_YANDEX_OAUTH_MARKER = "oauth_yandex"
_MIN_PASSWORD_LENGTH = 8
_MAX_PASSWORD_LENGTH = 128
_DUMMY_PASSWORD_HASH = hash_password("timing-padding")


def _normalize_email(email: str) -> str:
    if not isinstance(email, str):
        raise ValueError("Укажите email")
    normalized = email.strip().lower()
    if "@" not in normalized or normalized.startswith("@") or normalized.endswith("@"):
        raise ValueError("Некорректный email")
    local, _, domain = normalized.partition("@")
    if not local or "." not in domain or " " in normalized:
        raise ValueError("Некорректный email")
    return normalized


def _check_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < _MIN_PASSWORD_LENGTH:
        raise ValueError(f"Пароль должен быть не короче {_MIN_PASSWORD_LENGTH} символов")
    if len(password) > _MAX_PASSWORD_LENGTH:
        raise ValueError(f"Пароль должен быть не длиннее {_MAX_PASSWORD_LENGTH} символов")
    return password


class AuthService:
    def __init__(self,
                 user_repo: Any,
                 token_repo: Any):
        self.users = user_repo
        self.tokens = token_repo

    def register(self,
                 email: str,
                 password: str,
                 name: str) -> dict:
        """Регистрирует нового пользователя по email и паролю."""
        normalized_email = _normalize_email(email)
        checked_password = _check_password(password)
        clean_name = self._clean_name(name)

        if self.users.get_by_email(normalized_email):
            raise ValueError("Пользователь с таким email уже существует")

        user_id = self.users.create(
            email=normalized_email,
            password_hash=hash_password(checked_password),
            name=clean_name,
        )
        return self._issue_session(user_id=user_id, email=normalized_email, name=clean_name)

    def authenticate(self,
                     email: str,
                     password: str) -> dict:
        """Вход по email и паролю."""
        normalized_email = email.strip().lower() if isinstance(email, str) else ""
        user = self.users.get_by_email(normalized_email) if normalized_email else None
        if not user:
            verify_password(password if isinstance(password, str) else "", _DUMMY_PASSWORD_HASH)
            raise PermissionError("Неверный email или пароль")

        if not user.password_hash or user.password_hash == _YANDEX_OAUTH_MARKER:
            raise PermissionError(
                "Этот аккаунт создан через Яндекс. Войдите через Яндекс ID."
            )

        if not verify_password(password if isinstance(password, str) else "", user.password_hash):
            raise PermissionError("Неверный email или пароль")

        if needs_rehash(user.password_hash):
            self.users.update_password_hash(
                user_id=user.id,
                password_hash=hash_password(password),
            )

        return self._issue_session(user_id=user.id, email=user.email, name=user.name)

    def refresh(self, refresh_token: str) -> dict:
        """
        Меняет refresh на новую пару.
        Повтор уже отозванного refresh гасит всю цепочку этой сессии.
        """
        if not isinstance(refresh_token, str) or not refresh_token or len(refresh_token) > 200:
            raise PermissionError("Недействительный refresh-токен")

        now = datetime.now(timezone.utc)
        next_refresh_token = new_refresh_token()
        state, row = self.tokens.rotate_refresh_token(
            token_hash=hash_refresh_token(refresh_token),
            new_token_hash=hash_refresh_token(next_refresh_token),
            expires_at=now + refresh_ttl(),
            now=now,
        )
        if state == "reused":
            raise PermissionError("Сессия отозвана. Войдите снова.")
        if state == "expired":
            raise PermissionError("Сессия истекла. Войдите снова.")
        if state != "rotated" or row is None:
            raise PermissionError("Недействительный refresh-токен")

        user = self.users.get_by_id(row.user_id)
        if user is None:
            self.tokens.revoke_family(row.family_id)
            raise PermissionError("Недействительный refresh-токен")

        return self._session_response(
            user_id=user.id,
            email=user.email,
            name=user.name,
            refresh_token=next_refresh_token,
        )

    def logout(self,
               user_id: int,
               jti: str,
               access_expires_at: datetime,
               refresh_token: str | None = None) -> None:
        """Гасит текущий access сразу и все refresh этого пользователя."""
        self.tokens.revoke_access(
            jti=jti,
            user_id=user_id,
            expires_at=access_expires_at,
        )
        if refresh_token:
            row = self.tokens.get_refresh_by_hash(hash_refresh_token(refresh_token))
            if row is not None and row.user_id == user_id:
                self.tokens.revoke_family(row.family_id)
        self.tokens.revoke_all_refresh_for_user(user_id)

    def logout_refresh_only(self, refresh_token: str) -> None:
        """Гасит сессии по одному refresh, когда access уже истёк и Bearer не пройти."""
        if not isinstance(refresh_token, str) or not refresh_token or len(refresh_token) > 200:
            return
        row = self.tokens.get_refresh_by_hash(hash_refresh_token(refresh_token))
        if row is None:
            return
        self.tokens.revoke_all_refresh_for_user(row.user_id)

    def get_profile(self,
                    user_id: int) -> dict:
        """Возвращает публичный профиль пользователя."""
        user = self.users.get_by_id(user_id)
        if not user:
            raise ValueError("Пользователь не найден")
        return {
            "user_id": user.id,
            "email": user.email,
            "name": user.name
        }

    def update_profile(self,
                       user_id: int,
                       name: str) -> dict:
        """Обновляет отображаемое имя пользователя."""
        clean_name = self._clean_name(name)
        self.users.update_name(user_id=user_id, name=clean_name)
        return self.get_profile(user_id)

    def login_with_yandex(self,
                          yandex_id: str,
                          email: str,
                          name: str) -> dict:
        """
        Вход через Яндекс.
        Уже существующий email с паролем сам не привязываем: иначе чужой Яндекс
        забирает локальный аккаунт.
        """
        if not yandex_id:
            raise PermissionError("Яндекс не вернул идентификатор пользователя")

        normalized_email = _normalize_email(email)
        clean_name = self._clean_name(name)

        user = self.users.get_by_yandex_id(yandex_id)
        if user:
            return self._issue_session(user_id=user.id, email=user.email, name=user.name)

        existing_by_email = self.users.get_by_email(normalized_email)
        if existing_by_email:
            raise PermissionError(
                "Аккаунт с этим email уже зарегистрирован. Войдите по паролю."
            )

        new_user_id = self.users.create(
            email=normalized_email,
            password_hash=_YANDEX_OAUTH_MARKER,
            name=clean_name,
            yandex_id=yandex_id,
        )
        return self._issue_session(user_id=new_user_id, email=normalized_email, name=clean_name)

    def _issue_session(self,
                       user_id: int,
                       email: str,
                       name: str) -> dict:
        refresh_token = new_refresh_token()
        self.tokens.store_refresh(
            user_id=user_id,
            token_hash=hash_refresh_token(refresh_token),
            family_id=new_family_id(),
            expires_at=datetime.now(timezone.utc) + refresh_ttl(),
        )
        return self._session_response(user_id, email, name, refresh_token)

    @staticmethod
    def _session_response(user_id: int,
                          email: str,
                          name: str,
                          refresh_token: str) -> dict:
        access_token, _jti, _expires_at = create_access_token(user_id)
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": int(access_ttl().total_seconds()),
            "user_id": user_id,
            "email": email,
            "name": name,
        }

    @staticmethod
    def _clean_name(name: str) -> str:
        if not isinstance(name, str):
            raise ValueError("Имя не может быть пустым")
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Имя не может быть пустым")
        if len(clean_name) > 255:
            raise ValueError("Имя слишком длинное")
        return clean_name