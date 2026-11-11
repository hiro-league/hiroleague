"""The database helpers (db.py): the connection settings, and run_db() for async code."""

import asyncio
import threading

import pytest
from sqlalchemy import text
from sqlmodel import Session

from hiro_extension_kit.db import BUSY_TIMEOUT_MS, engine, run_db
from hiro_extension_kit.models import Setting


def test_every_connection_waits_for_the_lock_and_checks_keys():
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA busy_timeout")).scalar() == BUSY_TIMEOUT_MS
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"


def test_run_db_works_off_the_loop_and_keeps_what_it_commits():
    def add(session: Session, name: str) -> int:
        session.add(Setting(key="db-test", value=name))
        session.commit()
        return threading.get_ident()

    async def main():
        return await run_db(add, "Kept")

    assert asyncio.run(main()) != threading.get_ident()
    with Session(engine) as s:
        assert s.get(Setting, "db-test").value == "Kept"


def test_run_db_drops_what_it_did_not_commit_and_passes_errors_on():
    def fail(session: Session) -> None:
        session.add(Setting(key="db-test", value="Lost"))
        session.flush()
        raise ValueError("stop")

    with pytest.raises(ValueError, match="stop"):
        asyncio.run(run_db(fail))
    with Session(engine) as s:
        assert s.get(Setting, "db-test") is None
