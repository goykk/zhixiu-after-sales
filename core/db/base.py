from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from services.api.app.config import settings


class Base(DeclarativeBase):
    pass


def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def _ensure_sqlite_dir(url: str) -> None:
    if not url.startswith("sqlite"):
        return
    database = make_url(url).database
    if not database or database == ":memory:":
        return
    Path(database).expanduser().parent.mkdir(parents=True, exist_ok=True)


def init_engine(url: str) -> Engine:
    """Create the engine and rebind ``SessionLocal`` so callers always share one bind target."""
    global engine
    if url.startswith("sqlite"):
        _ensure_sqlite_dir(url)
        created = create_engine(
            url, connect_args={"check_same_thread": False}, pool_pre_ping=True
        )
        event.listen(created, "connect", _enable_sqlite_foreign_keys)
    else:
        created = create_engine(url, pool_pre_ping=True)
    SessionLocal.configure(bind=created)
    engine = created
    return created


SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False, future=True)
engine: Engine = init_engine(settings.database_url)


def create_all() -> None:
    import core.db.models  # noqa: F401  # 注册全部表

    try:
        # Upload 由多模态任务扩展；未就绪时跳过，存在时一并建表。
        import core.multimodal.uploads  # noqa: F401
    except ModuleNotFoundError:
        pass
    _ensure_sqlite_dir(str(engine.url))
    Base.metadata.create_all(engine)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()