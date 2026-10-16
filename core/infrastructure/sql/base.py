import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from core.infrastructure.sql.schema import metadata

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./hub_mvp.db")

engine = create_engine(
    DATABASE_URL, 
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def init_db():
    """Создает таблицы в базе данных, если они еще не существуют."""
    metadata.create_all(bind=engine)

def get_db():
    """Генератор сессии БД для эндпоинтов FastAPI."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()