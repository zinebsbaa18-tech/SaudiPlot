"""Database engine and session plumbing.

Everything here works from a SQLAlchemy URL only, so swapping SQLite for
PostgreSQL later is a configuration change. SQLite-specific arguments are
applied conditionally and never leak into models or services.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import DateTime, create_engine, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    pass


class UTCDateTime(TypeDecorator):
    """Timezone-aware UTC datetimes over a portable naive column.

    Binds aware datetimes as naive UTC (what SQLite and ``timestamp without
    time zone`` store) and returns them as aware UTC, so application code never
    mixes naive and aware values.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime rejected; use timezone-aware UTC datetimes")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


def utcnow() -> datetime:
    return datetime.now(UTC)


def create_database_engine(database_url: str) -> Engine:
    url = make_url(database_url)
    kwargs: dict = {}
    if url.get_backend_name() == "sqlite":
        # FastAPI may serve a request on a different thread than the one that
        # created the connection; in-memory databases additionally need a
        # single shared connection to see the same schema everywhere.
        kwargs["connect_args"] = {"check_same_thread": False}
        if not url.database or url.database == ":memory:":
            kwargs["poolclass"] = StaticPool
        else:
            # url.database is the actual file path for every sqlite URL form
            # (driver-qualified sqlite+pysqlite:/// included).
            Path(url.database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url, **kwargs)
    if url.get_backend_name() == "sqlite":
        # SQLite leaves foreign keys unenforced per connection; without this,
        # projects.session_id would be documentation, not a constraint.
        event.listen(engine, "connect", _sqlite_enable_foreign_keys)
    return engine


def _sqlite_enable_foreign_keys(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
