import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

BACKEND_DIR = Path(__file__).resolve().parent


def _resolve_database_url() -> str:
    """
    Resolve the database URL from the environment.

    Defaults to a local SQLite file next to the backend code for development.
    PostgreSQL URLs (e.g. from Render) are normalized to the psycopg2 driver;
    the legacy "postgres://" scheme is fixed automatically.
    """

    url = os.getenv("DATABASE_URL")

    if not url:
        return f"sqlite:///{BACKEND_DIR / 'documind.db'}"

    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)

    return url


DATABASE_URL = _resolve_database_url()

_connect_args = (
    {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
)

engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db():
    """
    Create all tables if they do not exist yet.
    """

    import models  # noqa: F401  (registers models on Base)

    Base.metadata.create_all(bind=engine)


def get_db():
    """
    FastAPI dependency yielding a database session per request.
    """

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
