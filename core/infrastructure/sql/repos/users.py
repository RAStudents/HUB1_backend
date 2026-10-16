from core.infrastructure.sql.schema import users_table


class UserRepository:
    def __init__(self, db_conn):
        self.db = db_conn

    def get_by_email(self, email: str):
        query = users_table.select().where(users_table.c.email == email)
        return self.db.execute(query).fetchone()

    def get_by_id(self, user_id: int):
        query = users_table.select().where(users_table.c.id == user_id)
        return self.db.execute(query).fetchone()

    def get_by_yandex_id(self, yandex_id: str):
        query = users_table.select().where(users_table.c.yandex_id == yandex_id)
        return self.db.execute(query).fetchone()

    def set_yandex_id(self, user_id: int, yandex_id: str) -> None:
        query = (
            users_table.update()
            .where(users_table.c.id == user_id)
            .values(yandex_id=yandex_id)
        )
        self.db.execute(query)
        self.db.commit()

    def update_name(self, user_id: int, name: str) -> None:
        query = (
            users_table.update()
            .where(users_table.c.id == user_id)
            .values(name=name)
        )
        self.db.execute(query)
        self.db.commit()

    def create(
        self, email: str, password_hash: str, name: str, yandex_id: str | None = None
    ) -> int:
        query = users_table.insert().values(
            email=email,
            password_hash=password_hash,
            name=name,
            yandex_id=yandex_id,
        )
        result = self.db.execute(query)
        self.db.commit()
        return result.inserted_primary_key[0]