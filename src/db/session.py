from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config import DB_URL

engine = create_engine(DB_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)


def init_db():
    """Ensure database is ready. Schema managed by Alembic migrations."""
    pass


def get_session():
    """Get a new database session."""
    return SessionLocal()
