"""SQLAlchemy database engine and session management."""

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

engine = create_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,   # validate connections before use (prevents stale-connection errors)
    pool_recycle=3600,    # recycle connections every hour
    pool_size=10,         # enough headroom for concurrent page loads
    max_overflow=5,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency that yields a database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_all_tables():
    """Build the full schema: the models' tables plus the db/ SQL extras.

    See app/schema.py. Idempotent; an existing database is left as it is.
    """
    from .schema import build_schema
    build_schema()
