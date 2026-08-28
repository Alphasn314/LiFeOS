"""Synchronous SQLAlchemy database boundary owned by LifeOS Core."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from lifeos.config import Settings, get_settings
from lifeos.models import Base


class Database:
    """Own an engine and short-lived unit-of-work sessions.

    The object is safe to construct once at process startup. ``session()`` commits
    on normal exit and rolls back on errors so application services cannot leak a
    partially completed transaction.
    """

    def __init__(self, database_url: str, *, echo: bool = False) -> None:
        url = make_url(database_url)
        engine_options: dict[str, Any] = {
            "echo": echo,
            "future": True,
            "pool_pre_ping": True,
        }

        if url.get_backend_name() == "sqlite":
            engine_options["connect_args"] = {"check_same_thread": False}
            if url.database in (None, "", ":memory:"):
                engine_options["poolclass"] = StaticPool

        self.engine: Engine = create_engine(url, **engine_options)
        if url.get_backend_name() == "sqlite":
            event.listen(self.engine, "connect", _enable_sqlite_foreign_keys)

        self.session_factory = sessionmaker(
            bind=self.engine,
            class_=Session,
            autoflush=False,
            expire_on_commit=False,
        )

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Yield one transactional session and close it deterministically."""

        session = self.session_factory()
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    def get_session(self) -> Iterator[Session]:
        """FastAPI-compatible dependency yielding a transactional session."""

        with self.session() as session:
            yield session

    def create_schema(self) -> None:
        """Create tables for ephemeral/test databases; production uses Alembic."""

        Base.metadata.create_all(self.engine)

    def drop_schema(self) -> None:
        """Drop all tables. Intended only for isolated tests."""

        Base.metadata.drop_all(self.engine)

    def dispose(self) -> None:
        """Release pooled database connections."""

        self.engine.dispose()


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_db(
    database_url: str | None = None,
    *,
    settings: Settings | None = None,
    echo: bool = False,
) -> Database:
    """Construct the Core database from an explicit URL or process settings."""

    resolved_settings = settings or get_settings()
    return Database(database_url or resolved_settings.database_url, echo=echo)
