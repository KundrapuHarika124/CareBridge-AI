"""SQLAlchemy engine and session. PostgreSQL only: booking relies on row locks."""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()

# prepare_threshold=None disables server-side prepared statements so the app also
# works behind transaction-mode connection poolers (for example Supabase's pooler).
engine = create_engine(
    _settings.sqlalchemy_url,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    connect_args={"prepare_threshold": None},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
