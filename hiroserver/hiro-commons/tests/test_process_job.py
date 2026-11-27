"""A held tree ends with its job, even once the launcher in its middle is gone (Windows' orphaned plugins)."""

from __future__ import annotations

import subprocess
import sys
import time

import pytest

from hiro_commons.process import is_running
from hiro_commons.process_job import ProcessJob

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="a job object is Windows'; elsewhere a process group")

# A launcher: starts a child once told to (so the job holds it first), prints the child's pid, then waits.
_LAUNCHER = (
    "import subprocess, sys, time\n"
    "sys.stdin.readline()\n"
    "c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
    "print(c.pid, flush=True)\n"
    "time.sleep(120)\n"
)


def _wait_gone(pid: int, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_running(pid):
            return True
        time.sleep(0.1)
    return False


def _held_tree() -> tuple[subprocess.Popen[str], ProcessJob, int]:
    launcher = subprocess.Popen(
        [sys.executable, "-c", _LAUNCHER],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    job = ProcessJob("a test tree")
    assert job.hold(launcher.pid)
    assert launcher.stdin is not None and launcher.stdout is not None
    launcher.stdin.write("go\n")
    launcher.stdin.flush()
    child = int(launcher.stdout.readline())
    return launcher, job, child


def test_the_child_of_a_dead_launcher_ends_when_the_job_closes() -> None:
    launcher, job, child = _held_tree()
    try:
        launcher.kill()  # the launcher alone: what a stop did before, leaving the real Python running
        launcher.wait(timeout=10)
        assert is_running(child)
        job.close()  # what Windows does when the holder ends, however it ends
        assert _wait_gone(child)
    finally:
        job.terminate()
        launcher.kill()


def test_terminate_ends_the_whole_tree() -> None:
    launcher, job, child = _held_tree()
    try:
        job.terminate()
        assert not job.holding
        launcher.wait(timeout=10)
        assert _wait_gone(child)
    finally:
        launcher.kill()
