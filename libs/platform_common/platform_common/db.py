"""Database access and a minimal SQL migration runner.

Each service owns its own database and login. Migrations are plain SQL files applied
in name order; an advisory lock lets several tasks start at once without racing.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

log = logging.getLogger(__name__)

_MIGRATION_LOCK_KEY = 72_410_001

OUTBOX_DDL = """
CREATE TABLE IF NOT EXISTS outbox (
    id           uuid PRIMARY KEY,
    event_type   text        NOT NULL,
    payload      jsonb       NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    published_at timestamptz,
    attempts     integer     NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS outbox_unpublished_idx ON outbox (created_at) WHERE published_at IS NULL;
"""

PROCESSED_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS processed_events (
    event_id     uuid PRIMARY KEY,
    event_type   text        NOT NULL,
    processed_at timestamptz NOT NULL DEFAULT now()
);
"""


class Database:
    def __init__(self, url: str, *, pool_size: int = 5, max_overflow: int = 5, application_name: str = "service"):
        self.engine: Engine = create_engine(
            url,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_pre_ping=True,
            pool_recycle=300,
            pool_timeout=10,
            connect_args={"application_name": application_name, "connect_timeout": 5},
        )
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def ping(self) -> bool:
        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:  # noqa: BLE001 - readiness must never raise
            log.warning("database ping failed", exc_info=True)
            return False

    def dispose(self) -> None:
        self.engine.dispose()


def run_migrations(
    engine: Engine,
    migrations_dir: Path,
    *,
    include_outbox: bool = False,
    include_processed_events: bool = False,
) -> list[str]:
    applied_now: list[str] = []
    with engine.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _MIGRATION_LOCK_KEY})
        conn.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        if include_outbox:
            conn.exec_driver_sql(OUTBOX_DDL)
        if include_processed_events:
            conn.exec_driver_sql(PROCESSED_EVENTS_DDL)
        done = {row[0] for row in conn.execute(text("SELECT name FROM schema_migrations"))}
        for path in sorted(Path(migrations_dir).glob("*.sql")):
            if path.name in done:
                continue
            log.info("applying migration %s", path.name)
            conn.exec_driver_sql(path.read_text(encoding="utf-8"))
            conn.execute(text("INSERT INTO schema_migrations (name) VALUES (:n)"), {"n": path.name})
            applied_now.append(path.name)
    return applied_now
