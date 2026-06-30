import os
from contextlib import contextmanager

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from models import Base


DEFAULT_DATABASE_URL = "sqlite:///atlas_local.db"


def get_database_url():
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def normalize_database_url(url):
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def create_database_engine(database_url=None):
    url = normalize_database_url(database_url or get_database_url())
    connect_args = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(url, future=True, pool_pre_ping=True, connect_args=connect_args)


engine = create_database_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db():
    Base.metadata.create_all(bind=engine)
    ensure_lightweight_migrations()


def ensure_lightweight_migrations():
    inspector = inspect(engine)
    if "businesses" not in inspector.get_table_names():
        return

    business_columns = {column["name"] for column in inspector.get_columns("businesses")}
    if "industry" not in business_columns:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE businesses ADD COLUMN industry VARCHAR(80) NOT NULL DEFAULT 'hvac'")
            )
    if "notification_email" not in business_columns:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE businesses ADD COLUMN notification_email VARCHAR(255) NOT NULL DEFAULT ''")
            )


@contextmanager
def session_scope():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()

