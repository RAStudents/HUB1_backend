# core/infrastructure/sql/base.py

import os
import logging
from sqlalchemy import create_engine, event, inspect, text
from uuid import uuid4
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
    migrate_dataset_public_ids(engine)
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


def migrate_dataset_public_ids(db_engine):
    """Stable random public IDs; internal keys and storage paths stay intact."""
    with db_engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(772018114)"))
        columns = {c["name"] for c in inspect(connection).get_columns("datasets")}
        if "public_id" not in columns:
            connection.execute(text("ALTER TABLE datasets ADD COLUMN public_id VARCHAR(36)"))
        rows = connection.execute(text("SELECT id FROM datasets WHERE public_id IS NULL")).fetchall()
        for row in rows:
            connection.execute(text("UPDATE datasets SET public_id = :public_id WHERE id = :id AND public_id IS NULL"), {"id": row.id, "public_id": str(uuid4())})
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_datasets_public_id ON datasets (public_id)"))
        if connection.dialect.name == "postgresql":
            connection.execute(text("ALTER TABLE datasets ALTER COLUMN public_id SET NOT NULL"))
        elif connection.dialect.name == "sqlite":
            for operation in ("INSERT", "UPDATE OF public_id"):
                name = "hub_dataset_public_id_" + operation.split()[0].lower()
                connection.execute(text(f"CREATE TRIGGER IF NOT EXISTS {name} BEFORE {operation} ON datasets WHEN NEW.public_id IS NULL BEGIN SELECT RAISE(ABORT, 'public_id is required'); END"))


def get_db():
    """Генератор сессии БД для FastAPI Depends."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
