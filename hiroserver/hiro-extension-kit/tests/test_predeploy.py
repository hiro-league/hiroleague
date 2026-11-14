"""A deploy's safety steps (predeploy.py): the copy before a deploy, the migrations tried on a copy, and the database put
back when the new version isn't healthy.

Shared-code plan, step 1: every app's tests had this file; it is tested once, here. That an app's own migrations run on a
copy of its database at head and lose nothing needs the app's migrations: the contract's
(contract.py `test_the_migrations_tried_on_a_copy_lose_nothing`). HomeHiro's second database (streams.db) stays in its
tests."""

import sqlite3
from pathlib import Path

from hiro_extension_kit import predeploy

STAMP = "pre-deploy-20261105-120000Z"


def _db(path: Path, rows: int, table: str = "person") -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA wal_autocheckpoint=0")  # what is written stays in the WAL file, as on a busy live copy
    con.execute(f"CREATE TABLE {table} (id TEXT)")
    con.executemany(f"INSERT INTO {table} VALUES (?)", [(str(i),) for i in range(rows)])
    con.commit()
    return con


def test_the_copy_has_what_is_still_in_the_wal_file(tmp_path):
    live = _db(tmp_path / predeploy.DB, 3)
    assert (tmp_path / f"{predeploy.DB}-wal").stat().st_size > 0
    predeploy.snapshot(tmp_path, STAMP)
    live.close()
    assert predeploy.counts(tmp_path / predeploy.BACKUPS / f"{STAMP}.db") == {"person": 3}


def test_only_the_last_copies_are_kept(tmp_path):
    _db(tmp_path / predeploy.DB, 1).close()
    for n in range(predeploy.KEEP + 2):
        predeploy.snapshot(tmp_path, f"pre-deploy-2026101{n}-120000Z")
    kept = sorted(p.name for p in (tmp_path / predeploy.BACKUPS).iterdir())
    assert kept == [f"pre-deploy-2026101{n}-120000Z.db" for n in range(2, predeploy.KEEP + 2)]


def test_no_database_yet_is_nothing_to_copy(tmp_path):
    assert predeploy.snapshot(tmp_path, STAMP) == [f"No {predeploy.DB} yet: nothing to copy"]
    assert not (tmp_path / predeploy.BACKUPS).exists()


def test_a_table_gone_or_with_fewer_rows_is_a_loss():
    before = {"person": 12, "device": 5, "job": 4}
    assert predeploy.losses(before, {"person": 12, "device": 6, "job": 4}) == []
    assert predeploy.losses(before, {"person": 0, "device": 5}) == [
        f"{predeploy.DB}: table job is gone (it had 4 rows)", f"{predeploy.DB}: table person has 0 rows, it had 12"]
    assert predeploy.losses(before, {"person": 0, "device": 5}, frozenset({"person", "job"})) == []


def test_a_migration_that_fails_stops_the_trial(tmp_path):
    copy = tmp_path / "copy.db"
    con = sqlite3.connect(copy)
    con.execute("CREATE TABLE alembic_version (version_num TEXT)")
    con.execute("INSERT INTO alembic_version VALUES ('not-a-revision')")  # Alembic can't go on from there
    con.commit()
    con.close()
    _before, problems, _took = predeploy.trial(copy, tmp_path / "trial")
    assert len(problems) == 1 and problems[0].startswith("the migration failed")


def test_restore_puts_it_back_and_drops_the_new_versions_wal(tmp_path):
    _db(tmp_path / predeploy.DB, 2).close()
    predeploy.snapshot(tmp_path, STAMP)
    # the new version migrated and wrote meanwhile, and left its WAL file
    (tmp_path / predeploy.DB).unlink()
    _db(tmp_path / predeploy.DB, 9, "other").close()
    (tmp_path / f"{predeploy.DB}-wal").write_bytes(b"the new version's")
    assert predeploy.restore(tmp_path, STAMP) == [f"Put {predeploy.DB} back from {STAMP}.db"]
    assert not (tmp_path / f"{predeploy.DB}-wal").exists()
    assert predeploy.counts(tmp_path / predeploy.DB) == {"person": 2}
    assert (tmp_path / predeploy.BACKUPS / f"{STAMP}.db").exists()  # the copy stays with the others
    assert predeploy.restore(tmp_path, "pre-deploy-none") == ["No copy to put back"]
