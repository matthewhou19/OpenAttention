import logging

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import sessionmaker

from src.config import DB_URL

logger = logging.getLogger(__name__)

engine = create_engine(DB_URL, echo=False, connect_args={"timeout": 15})
SessionLocal = sessionmaker(bind=engine)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    mode = cursor.fetchone()[0]
    cursor.close()
    if mode != "wal":
        logger.warning("Failed to enable WAL mode, got: %s", mode)


def init_db():
    """Ensure database is ready. Schema managed by Alembic migrations."""
    if not inspect(engine).has_table("alembic_version"):
        raise RuntimeError("Database not initialized. Run: alembic upgrade head")


def get_session():
    """Get a new database session."""
    return SessionLocal()
