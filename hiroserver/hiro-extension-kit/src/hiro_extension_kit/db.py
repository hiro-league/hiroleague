"""The app's SQLite database, DATA_DIR/<app>.db (`engine`), its schema managed by the app's Alembic migrations
(`<the app's package>/migrations`).

Database work doesn't belong on the event loop: a query that waits for the write lock, or reads many
rows, stops every other request and background task meanwhile. From async code, use `run_db()`.

`Database` is one SQLite file with its migrations; the app's own one is made here when the module loads (`main`), and
`engine`, `get_session`, `run_db` and `migrate` are its. An app with a second file makes another `Database` for it.
"""

import asyncio
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, TypeVar

from alembic import command
from alembic.config import Config
from sqlalchemy import event
from sqlmodel import Session, create_engine

from . import identity

T = TypeVar("T")

# How long a write waits for another one to finish before failing with "database is locked"
# (Python's sqlite3 default, made explicit).
BUSY_TIMEOUT_MS = 5000


class Database:
    """One SQLite file (made with its folder if missing) and the Alembic migrations that keep its schema.

    `foreign_keys`: SQLite checks them (off by default in SQLite). `synchronous`: SQLite's setting, e.g. "NORMAL" for a
    file of many rows written all day (HomeHiro's streams.db: no fsync per commit; with WAL the file can't be corrupted
    by it, a power cut can lose the rows of the last moment). Backend kit step 5: HomeHiro's second file."""

    def __init__(self, path: Path, migrations: Path, *, foreign_keys: bool = True, synchronous: str | None = None) -> None:
        self.path = path
        self.migrations = migrations
        self.foreign_keys = foreign_keys
        self.synchronous = synchronous
        path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{path.as_posix()}", connect_args={"check_same_thread": False})
        event.listen(self.engine, "connect", self._pragmas)

    def _pragmas(self, conn, _record) -> None:
        # WAL lets the UI read while a sync writes.
        conn.execute("PRAGMA journal_mode=WAL")
        if self.foreign_keys:
            conn.execute("PRAGMA foreign_keys=ON")
        if self.synchronous:
            conn.execute(f"PRAGMA synchronous={self.synchronous}")
        conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")

    def get_session(self) -> Iterator[Session]:
        with Session(self.engine) as session:
            yield session

    async def run_db(self, fn: Callable[..., T], *args: Any) -> T:
        """Run `fn(session, *args)` in a worker thread, with a session of its own, and return its result.
        `fn` commits what it wants kept; anything else is rolled back when the session closes."""

        def work() -> T:
            with Session(self.engine) as session:
                return fn(session, *args)

        return await asyncio.to_thread(work)

    def migrate(self) -> None:
        """Bring the database's schema up to date (run on every start)."""
        cfg = Config()
        cfg.set_main_option("script_location", str(self.migrations))
        command.upgrade(cfg, "head")


_app = identity.app()
# Dev: backend/data/ (git-ignored). Container: /app/data, a volume so the database survives rebuilds.
main = Database(_app.data_dir / f"{_app.name}.db", _app.package / "migrations")
MIGRATIONS = main.migrations
engine = main.engine
get_session = main.get_session
run_db = main.run_db
migrate = main.migrate
