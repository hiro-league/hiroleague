"""Log files (logs.py): kept in DATA_DIR/logs, problems also in their own file, and nothing that goes
wrong escapes them: a crashed request (uvicorn's loggers), a thread, a warning from anywhere."""

import logging
import sys
import threading

import pytest

from hiro_extension_kit import logs


@pytest.fixture
def log_dir(tmp_path):
    """setup() into a folder of the test's own; its files are closed and the hooks put back afterwards."""
    hooks = sys.excepthook, threading.excepthook, sys.unraisablehook
    # setup() also opens the root logger to INFO. These tests share a process with the rest of the workspace, whose
    # own loggers count on the root staying at WARNING, so the level goes back as well.
    root_level = logging.getLogger().level
    yield tmp_path
    logs.close()
    logging.getLogger().setLevel(root_level)
    logging.captureWarnings(False)
    sys.excepthook, threading.excepthook, sys.unraisablehook = hooks


def read(folder, name):
    for h in logging.getLogger().handlers:
        h.flush()
    path = folder / name
    return path.read_text(encoding="utf-8") if path.exists() else ""


def test_everything_goes_to_the_log_and_problems_also_to_their_own_file(log_dir):
    logs.setup(log_dir)
    logging.getLogger("testapp.people").info("People: Maro is now tracked")
    logging.getLogger("testapp.ha").warning("HA connection lost (timeout); retrying in 5 s")
    everything, errors = read(log_dir, "testapp.log"), read(log_dir, "testapp-errors.log")
    assert "INFO testapp.people: People: Maro is now tracked" in everything
    assert "WARNING testapp.ha: HA connection lost" in everything and "HA connection lost" in errors
    assert "Maro" not in errors


def test_a_request_that_crashed_is_in_the_errors_file(log_dir):
    """uvicorn's loggers keep their lines to themselves (propagate=False), so they get the files too."""
    logs.setup(log_dir)
    uvicorn = logging.getLogger("uvicorn")
    uvicorn.propagate = False  # as uvicorn sets it up when it runs the app
    try:
        raise ValueError("boom")
    except ValueError:
        logging.getLogger("uvicorn.error").exception("Exception in ASGI application")
    finally:
        uvicorn.propagate = True
    errors = read(log_dir, "testapp-errors.log")
    assert "ERROR uvicorn.error: Exception in ASGI application" in errors
    assert "ValueError: boom" in errors  # with its traceback


def test_an_uncaught_exception_in_a_thread_is_in_the_errors_file(log_dir):
    logs.setup(log_dir)

    def work():
        raise RuntimeError("worker died")

    t = threading.Thread(target=work, name="sampler")
    t.start()
    t.join()
    errors = read(log_dir, "testapp-errors.log")
    assert "Uncaught exception in thread sampler: worker died" in errors
    assert "RuntimeError: worker died" in errors


def test_setting_up_again_does_not_write_each_line_twice(log_dir):
    logs.setup(log_dir)
    logs.setup(log_dir)
    logging.getLogger("testapp.test").warning("once")
    assert read(log_dir, "testapp-errors.log").count("once") == 1
