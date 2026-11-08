# core/infrastructure/sql/repos/users.py

import logging
from core.infrastructure.sql.schema import users_table


logger = logging.getLogger(__name__)


class UserRepository:
    def __init__(self, db_conn):
        self.db = db_conn

    def get_by_email(self,
                     email: str):
        query = users_table.select().where(users_table.c.email == email)
        return self.db.execute(query).fetchone()

    def get_by_id(self,
                  user_id: int):
        query = users_table.select().where(users_table.c.id == user_id)
        return self.db.execute(query).fetchone()

    def get_by_yandex_id(self,
                         yandex_id: str):
        query = users_table.select().where(users_table.c.yandex_id == yandex_id)
        return self.db.execute(query).fetchone()

    def create(self,
               email: str,
               password_hash: str,
               name: str,
               yandex_id: str | None = None) -> int:
        """Создаёт пользователя и возвращает его id."""
        query = users_table.insert().values(
            email=email,
            password_hash=password_hash,
            name=name,
            yandex_id=yandex_id,
        )
        result = self.db.execute(query)
        self.db.commit()
        return result.inserted_primary_key[0]

    def update_name(self,
                    user_id: int,
                    name: str) -> None:
        """Обновляет отображаемое имя пользователя."""
        query = (
            users_table.update()
            .where(users_table.c.id == user_id)
            .values(name=name)
        )
        self.db.execute(query)
        self.db.commit()

    def set_yandex_id(self,
                      user_id: int,
                      yandex_id: str) -> None:
        """Привязывает Яндекс ID к существующему аккаунту."""
        query = (
            users_table.update()
            .where(users_table.c.id == user_id)
            .values(yandex_id=yandex_id)
        )
        self.db.execute(query)
        self.db.commit()
