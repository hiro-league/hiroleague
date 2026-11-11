"""Test setup: pytest loads this before any test module here, so before a module of the kit reads which app it is.

The kit is told it is an app called `testapp`, with an empty data folder of this run's own (never a real app's:
the tests write log files and rows there). `identity.setup`, not the package's `setup`: that one also changes how the
SDK's workers log their failures, for the whole process, and the SDK's own tests run in the same process.
"""

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

from hiro_extension_kit import identity

DATA_DIR = Path(tempfile.mkdtemp(prefix="hiro-kit-tests-")).resolve()
identity.setup(name="testapp", title="TestApp", package=Path(__file__).parent, data_dir=DATA_DIR,
               static_dir=DATA_DIR / "static")


@pytest.fixture(autouse=True, scope="session")
def _the_test_database():
    """The kit ships no migrations (each app's make its tables): the tests' database gets the kit's tables directly."""
    from hiro_extension_kit import db, logs
    from hiro_extension_kit.models import Setting

    assert DATA_DIR in Path(db.engine.url.database or "").resolve().parents
    Setting.__table__.create(db.engine, checkfirst=True)  # type: ignore[attr-defined]
    yield
    db.engine.dispose()
    logs.close()  # Windows can't delete an open file
    try:
        shutil.rmtree(DATA_DIR)
    except OSError as e:
        print(f"\nCould not remove the test data folder {DATA_DIR}: {e}", file=sys.stderr)


@pytest.fixture(autouse=True)
def _empty_tables():
    """Every test starts with empty tables: a row one test kept is not there for the next."""
    yield
    from sqlmodel import Session, delete

    from hiro_extension_kit import db
    from hiro_extension_kit.models import Setting

    with Session(db.engine) as session:
        session.exec(delete(Setting))  # type: ignore[call-overload]
        session.commit()
