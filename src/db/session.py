from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from src.config import DB_URL

engine = create_engine(DB_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)


def init_db():
    """Ensure database is ready. Schema managed by Alembic migrations."""
    if not inspect(engine).has_table("alembic_version"):
        raise RuntimeError("Database not initialized. Run: alembic upgrade head")


def get_session():
    """Get a new database session."""
    return SessionLocal()
