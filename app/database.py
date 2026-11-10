import os
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError, TimeoutError as PoolTimeoutError
from sqlalchemy.orm import DeclarativeBase, sessionmaker


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "sqlite:///./dashboard-dev.db")
    if "[REDACTED]" in url:
        raise RuntimeError("DATABASE_URL contains the redacted password placeholder; replace it with the real database password")
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


DATABASE_URL = _database_url()
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=int(os.getenv("DB_POOL_SIZE", "5")), max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "5")), pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "5")), pool_recycle=1800, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


@contextmanager
def session_scope():
    try:
        session = SessionLocal()
    except PoolTimeoutError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="Database connection pool is busy; retry shortly") from exc
    try:
        yield session
        session.commit()
    except PoolTimeoutError as exc:
        session.rollback()
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="Database connection pool is busy; retry shortly") from exc
    except SQLAlchemyError:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    from app import db_models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    # Migration-safe: add conversation_id to chat_messages if the table already
    # existed without it (no Alembic in this project). Existing rows get NULL.
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    if "chat_messages" in inspector.get_table_names():
        columns = {col["name"] for col in inspector.get_columns("chat_messages")}
        if "conversation_id" not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE chat_messages ADD COLUMN conversation_id VARCHAR(64)"))
