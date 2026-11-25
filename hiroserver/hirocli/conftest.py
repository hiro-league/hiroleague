"""Pytest session-wide configuration for hirocli.

Ensures the shared structlog pipeline is initialized once before any test
imports modules that call ``log.fineinfo(...)`` / ``log.info(...)``. Without
``Logger.setup()`` the lazy-bound logger resolves to ``BoundLoggerFilteringAtNotset``,
which lacks the custom ``fineinfo`` method and raises ``AttributeError`` at runtime.

It also keeps the whole run out of this machine's real Hiro data: the workspace registry and every workspace resolve
inside a temporary folder of the run's own (see ``TEST_DATA_DIR``), and a test that still starts the log in a real
workspace fails.
"""

from __future__ import annotations

import atexit
import os
import shutil
import signal
import tempfile
from pathlib import Path

import pytest
from platformdirs import user_data_dir

from hiro_commons import logging_foundation
from hiro_commons.log import Logger
from hirocli.constants import APP_NAME, ENV_DATA_DIR
from hirocli.domain import workspace as _workspace

# Force LangSmith tracing OFF for the whole test session. The graphs and the memory library
# trace their runs (``hiro_memory.tracing``), a no-op only when tracing is disabled. Tests drive
# them with fakes (no real LLM calls), so with tracing inherited from the dev shell each test
# posts a hollow, empty trace to LangSmith. Clearing the switches here (vs. only when
# unset) guarantees no test ever writes to LangSmith regardless of the developer's env;
# non-test runs are untouched since this only mutates the pytest process environment.
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"

Logger.set_level("DEBUG")
Logger.setup(console=False)


def _real_folders() -> tuple[Path, ...]:
    """This machine's real Hiro data: the data folder (the platform's, and HIRO_DATA_DIR's when set) and every
    workspace its registry names (on the PC those live elsewhere, under C:\\hiro\\data\\envN). Read once, before the
    run is pointed away from them."""
    data_dirs = [Path(user_data_dir(APP_NAME, appauthor=False))]
    if os.environ.get(ENV_DATA_DIR, "").strip():
        data_dirs.append(Path(os.environ[ENV_DATA_DIR].strip()))
    found = list(data_dirs)
    for data_dir in data_dirs:
        try:
            registry = _workspace.WorkspaceRegistry.model_validate_json(
                (data_dir / _workspace.REGISTRY_FILENAME).read_text(encoding="utf-8"))
        except (OSError, ValueError):  # no registry here (a fresh machine) or one we can't read: the folder still counts
            continue
        found += [Path(entry.path) for entry in registry.workspaces.values()]
    return tuple(folder.resolve() for folder in found)


REAL_FOLDERS = _real_folders()

# Why: a CLI test (`CliRunner().invoke(app, ...)`) runs the `hiro` callback, which resolves the default workspace from
# the real registry and starts the log there (`Logger.start`). The foundation is process-wide, so every later test in
# that worker logged into the real workspace's `cli-<day>.jsonl` too: on Simone the deploy's check filled live's log
# store with test failures ("disk full", "owners-msg") that `hiro logs problems` showed as live problems. The
# platform's data folder is replaced here for the whole run (each xdist worker gets its own), and HIRO_DATA_DIR is
# cleared, so the registry starts empty and every workspace a test makes lands in this temporary folder.
TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="hiro-test-data-"))
atexit.register(shutil.rmtree, TEST_DATA_DIR, ignore_errors=True)
os.environ.pop(ENV_DATA_DIR, None)
_workspace.user_data_dir = lambda *args, **kwargs: str(TEST_DATA_DIR)


def in_real_folder(folder: Path) -> bool:
    """Whether `folder` is this machine's real Hiro data, or inside it."""
    folder = Path(folder).resolve()
    return any(folder == real or folder.is_relative_to(real) for real in REAL_FOLDERS)


@pytest.fixture
def real_hiro_data():
    """`in_real_folder`, for a test that checks where something was written."""
    return in_real_folder


@pytest.fixture(autouse=True)
def _logs_stay_out_of_real_workspaces():
    """After every test: the log foundation writes nowhere real. A test that started it in a real workspace fails here,
    by name, and the file is closed so the rest of the run doesn't follow it there."""
    yield
    started = logging_foundation.where()
    if started is not None and in_real_folder(started[0]):
        Logger.close()
        pytest.fail(f"This test started the log in a real workspace ({started[0]}): give it a folder of its own "
                    "(tmp_path) instead.")


def pytest_configure(config) -> None:
    """In a pytest-xdist worker, ignore SIGINT, as scripts/run-tests.sh does for the main process.

    The phantom console Ctrl-C that onnxruntime's handler sends mid-suite (run-tests.sh says why) reaches every
    process on the console, and a worker doesn't inherit the main process's SIG_IGN: in parallel runs every worker
    died of a KeyboardInterrupt about 80% through. Workers still stop with the run: Ctrl-Break or closing the
    terminal ends the main process, and xdist ends its workers.
    """
    if hasattr(config, "workerinput"):
        signal.signal(signal.SIGINT, signal.SIG_IGN)
