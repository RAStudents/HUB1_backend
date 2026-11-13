# core/infrastructure/sql/base.py

import os
import logging
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import declarative_base, sessionmaker

from core.infrastructure.sql.schema import metadata


logger = logging.getLogger(__name__)


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./hub_mvp.db")

_connect_args = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}

engine = create_engine(DATABASE_URL, connect_args=_connect_args)
if "sqlite" in DATABASE_URL:
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db() -> None:
    """Создаёт все таблицы в базе данных (если они ещё не существуют)."""
    metadata.create_all(bind=engine)
    membership_columns = {
        column["name"] for column in inspect(engine).get_columns("memberships")
    }
    if "status" not in membership_columns:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE memberships "
                    "ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'accepted'"
                )
            )
    export_columns = {column["name"] for column in inspect(engine).get_columns("exports")}
    missing_export_columns = {
        "total_samples": "INTEGER NOT NULL DEFAULT 0",
        "stage": "VARCHAR(50) NOT NULL DEFAULT 'processing'",
    }
    if missing_export_columns.keys() - export_columns:
        with engine.begin() as connection:
            for column_name, column_definition in missing_export_columns.items():
                if column_name not in export_columns:
                    connection.execute(
                        text(
                            f"ALTER TABLE exports "
                            f"ADD COLUMN {column_name} {column_definition}"
                        )
                    )
            if "total_samples" not in export_columns:
                connection.execute(
                    text(
                        "UPDATE exports SET total_samples = exported_samples "
                        "WHERE status = 'completed' AND total_samples = 0"
                    )
                )
    for table in metadata.tables.values():
        for index in table.indexes:
            index.create(bind=engine, checkfirst=True)


def get_db():
    """Генератор сессии БД для FastAPI Depends."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
