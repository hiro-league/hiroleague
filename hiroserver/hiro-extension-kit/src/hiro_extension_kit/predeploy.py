"""A deploy's safety steps, run by the app's deploy.sh in the new image before it replaces the running one (each app's
README, "How deploy works"). The live database is the family's only copy between the nightly backups:

- DATA_DIR/<app>.db: copied before every deploy, the last KEEP copies kept, and its migrations tried on a copy.

Steps, each `python -m <app>.predeploy <step> <stamp>` (stamp: pre-deploy-<time>, the copies' names; the app's
predeploy.py runs `main()` here):

- `snapshot`: the copy, made with SQLite's backup (live runs in WAL mode, so its newest changes may still be in the
  -wal file, which a plain copy of the file leaves out).
- `trial`: the new code's migrations run on another copy (as the app does on start), which is then checked: no table
  gone, none with fewer rows, and SQLite finds it sound. A migration meant to remove rows names its tables in
  ALLOW_ROW_LOSS ("trafficminute,servicehour"). Its last line says how long the migrations took
  (`migrations-seconds=<n>`), so deploy.sh waits long enough for the new version to start.
- `restore`: the database put back as `snapshot` copied it (the health check failed; the app is stopped).

What it does goes to the deploy's output; a step that fails exits 1, with the reason.

Backend kit, step 6: NetHiro's and TrainHiro's copies, the same but for the app's name. HomeHiro, with a second
database (streams.db), keeps its own steps and takes the helpers that are the same (copy_name, copy_db, counts, losses).
"""

import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

from . import identity

DB = f"{identity.app().name}.db"  # e.g. nethiro.db
BACKUPS = "deploy-backups"
KEEP = 5  # <app>.db copies made before a deploy, kept (the oldest go)
_OWN = ("alembic_version",)  # Alembic's own table: its row changes with every migration


def copy_name(stamp: str) -> str:
    return f"{stamp}.db"


def copy_db(source: Path, dest: Path) -> None:
    """A whole copy of a database, with what is still in its WAL file (SQLite's backup)."""
    src = sqlite3.connect(source)
    try:
        out = sqlite3.connect(dest)
        try:
            src.backup(out)
        finally:
            out.close()
    finally:
        src.close()


def snapshot(data_dir: Path, stamp: str) -> list[str]:
    """Copy the live database to DATA_DIR/deploy-backups, keeping the last KEEP copies. Returns what it did, in words."""
    folder = data_dir / BACKUPS
    live = data_dir / DB
    if not live.exists():
        return [f"No {DB} yet: nothing to copy"]
    folder.mkdir(parents=True, exist_ok=True)
    copy_db(live, folder / copy_name(stamp))
    for old in sorted(folder.glob("pre-deploy-*.db"))[:-KEEP]:  # their names sort by when they were made
        old.unlink()
    return [f"Copied {DB} to {folder / copy_name(stamp)}"]


def counts(db: Path) -> dict[str, int]:
    """Each table's rows, but Alembic's own."""
    con = sqlite3.connect(db)
    try:
        tables = [t for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")
                  if t not in _OWN]
        return {t: con.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}
    finally:
        con.close()


def losses(before: dict[str, int], after: dict[str, int], allowed: frozenset[str] = frozenset(), where: str = DB) -> list[str]:
    """What a migration lost, in words: tables gone, tables with fewer rows. Those in `allowed` may."""
    out = []
    for table, n in sorted(before.items()):
        if table in allowed:
            continue
        if table not in after:
            out.append(f"{where}: table {table} is gone (it had {n} rows)")
        elif after[table] < n:
            out.append(f"{where}: table {table} has {after[table]} rows, it had {n}")
    return out


def sound(db: Path) -> str:
    """SQLite's own check of a database: "ok", or what is wrong."""
    con = sqlite3.connect(db)
    try:
        return "; ".join(row[0] for row in con.execute("PRAGMA integrity_check"))
    finally:
        con.close()


def trial(copy: Path, work: Path, allowed: frozenset[str] = frozenset()) -> tuple[dict[str, int], list[str], float]:
    """Run the migrations on a copy of `copy` in `work` (emptied first, removed after). Returns the rows before, what
    went wrong, in words (none: it is safe), and the seconds it took."""
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    try:
        db = work / DB
        copy_db(copy, db)
        before = counts(db)
        started = time.monotonic()
        # a process of its own: the database's place is read once, when the kit's db module is first imported
        # (the app's package first: it tells the kit which app this is)
        done = subprocess.run([sys.executable, "-c", f"import {identity.app().name}; from hiro_extension_kit.db import migrate; migrate()"],
                              env={**os.environ, "DATA_DIR": str(work)}, capture_output=True, text=True)
        took = time.monotonic() - started
        if done.returncode:
            return before, [f"the migration failed:\n{done.stderr.strip()[-3000:]}"], took
        problems = losses(before, counts(db), allowed)
        if (said := sound(db)) != "ok":
            problems.append(f"SQLite finds the migrated copy of {DB} unsound: {said}")
        return before, problems, took
    finally:
        shutil.rmtree(work, ignore_errors=True)


def restore(data_dir: Path, stamp: str) -> list[str]:
    """Put the database back as `snapshot` copied it. The app must be stopped."""
    live, copy = data_dir / DB, data_dir / BACKUPS / copy_name(stamp)
    if not copy.exists():
        return ["No copy to put back"]
    # The WAL file goes first: SQLite would otherwise apply the new version's writes to the copy put back
    for extra in (live.with_name(live.name + "-wal"), live.with_name(live.name + "-shm")):
        extra.unlink(missing_ok=True)
    shutil.copyfile(copy, live)  # the copy stays, with the others
    return [f"Put {live.name} back from {copy.name}"]


def main(argv: list[str]) -> int:
    steps = ("snapshot", "trial", "restore")
    if len(argv) != 2 or argv[0] not in steps:
        print(f"usage: python -m {identity.app().name}.predeploy {'|'.join(steps)} <stamp>", file=sys.stderr)
        return 2
    step, stamp = argv
    data_dir = identity.app().data_dir
    folder = data_dir / BACKUPS
    try:
        if step == "snapshot":
            print(*snapshot(data_dir, stamp), sep="\n")
        elif step == "restore":
            print(*restore(data_dir, stamp), sep="\n")
        elif not (folder / copy_name(stamp)).exists():
            print(f"No {DB} yet: no migration to try")
            print("migrations-seconds=0")
        else:
            allowed = frozenset(t.strip() for t in os.environ.get("ALLOW_ROW_LOSS", "").split(",") if t.strip())
            before, problems, took = trial(folder / copy_name(stamp), folder / "trial", allowed)
            if problems:
                print("The new migrations are not safe on a copy of the live database:", *problems, sep="\n- ")
                return 1
            print(f"The new migrations ran on a copy of the live database in {took:.0f} s: {len(before)} tables, "
                  f"{sum(before.values())} rows, none lost")
            print(f"migrations-seconds={round(took)}")
    except (OSError, sqlite3.Error, RuntimeError) as e:
        print(f"{step} failed: {e}", file=sys.stderr)
        return 1
    return 0

