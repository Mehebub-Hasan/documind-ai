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


def ensure_schema_upgrades(engine) -> None:
    """
    Apply light in-place migrations for databases created before a column
    existed. create_all() only builds missing tables, so existing deployments
    (SQLite dev file or PostgreSQL on Render) would otherwise never gain the
    new columns.
    """

    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    table_names = inspector.get_table_names()

    if "documents" in table_names:
        column_names = {
            column["name"] for column in inspector.get_columns("documents")
        }

        if "summary" not in column_names:
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE documents ADD COLUMN summary TEXT")
                )

    if "users" in table_names:
        column_names = {column["name"] for column in inspector.get_columns("users")}

        if "is_verified" not in column_names:
            with engine.begin() as connection:
                # DEFAULT 1 backfills users that predate email verification
                # as verified, so existing accounts are not locked out.
                connection.execute(
                    text(
                        "ALTER TABLE users ADD COLUMN is_verified "
                        "BOOLEAN NOT NULL DEFAULT 1"
                    )
                )

        if "verification_code" not in column_names:
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE users ADD COLUMN verification_code VARCHAR")
                )

        if "code_expires_at" not in column_names:
            with engine.begin() as connection:
                connection.execute(
                    text("ALTER TABLE users ADD COLUMN code_expires_at DATETIME")
                )


def init_db():
    """
    Create all tables if they do not exist yet, then upgrade existing tables
    with columns added after the initial release.
    """

    import models  # noqa: F401  (registers models on Base)

    Base.metadata.create_all(bind=engine)
    ensure_schema_upgrades(engine)


def get_db():
    """
    FastAPI dependency yielding a database session per request.
    """

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
