from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.config import Settings
from core.models.entities import Base

ENGINE = None
SessionLocal = None


def init_engine(settings: Settings):
    global ENGINE, SessionLocal

    connect_args = {}
    if settings.db_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    ENGINE = create_engine(settings.db_url, connect_args=connect_args, future=True)
    SessionLocal = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False, expire_on_commit=False)
    return ENGINE


def init_db() -> None:
    if ENGINE is None:
        raise RuntimeError("Database engine is not initialized")
    Base.metadata.create_all(bind=ENGINE)


@contextmanager
def session_scope() -> Iterator[Session]:
    if SessionLocal is None:
        raise RuntimeError("Database session factory is not initialized")
    session: Session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Session:
    if SessionLocal is None:
        raise RuntimeError("Database session factory is not initialized")
    return SessionLocal()

