# core/infrastructure/sql/base.py

import os
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from core.infrastructure.sql.schema import metadata


logger = logging.getLogger(__name__)


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./hub_mvp.db")

_connect_args = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}

engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db() -> None:
    """Создаёт все таблицы в базе данных (если они ещё не существуют)."""
    metadata.create_all(bind=engine)
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
