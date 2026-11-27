"""hiro-work lock-refresh: its steps in order, the commit before the fresh installs (they install committed code only),
and the first failure stopping it. The steps' programs are faked: a test never runs uv, the check or a machine."""

import subprocess
import sys
from types import SimpleNamespace

import pytest

import hiro_work as hw
import lock_refresh as lr

MOVED = "uv.lock refreshed to the latest: 2 package(s) changed.\n  cryptography: 47.0.0 → 50.0.2\n  numpy: 2.4.4 → 2.5.5\n"


def sh(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          encoding="utf-8").stdout.strip()


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    """A task's checkout of the core on its branch, with the three files a refresh writes."""
    repo = tmp_path / "hiroleague"
    for f in lr.FILES:
        (repo / f).parent.mkdir(parents=True, exist_ok=True)
        (repo / f).write_text("old\n", encoding="utf-8")
    sh(tmp_path, "init", "-q", "-b", "main", str(repo))
    sh(repo, "config", "user.email", "t@t")
    sh(repo, "config", "user.name", "t")
    sh(repo, "add", ".")
    sh(repo, "commit", "-q", "-m", "main")
    sh(repo, "switch", "-q", "-c", "task/lock")
    monkeypatch.setattr(hw, "repo_dir", lambda env, r: repo)
    monkeypatch.setattr(hw, "TASKS", tmp_path / "tasks")
    monkeypatch.setattr(hw, "LOGS", tmp_path / "logs")
    monkeypatch.setattr(hw, "EVENTS", tmp_path / "logs" / "events.jsonl")
    hw.TASKS.mkdir(parents=True)
    hw.save(hw.Task(id="lock", title="lock", env=5, repos=["hiroleague"], state="working"))
    return repo


def fake(repo, ran, fail=""):
    """Each step's program: the refresh writes the lock and prints what moved; ``fail`` names one that fails."""

    def run(args, cwd):
        name = next(n for n, a in lr.steps(hw.bash(), sys.executable) if a == list(args))
        ran.append((name, sh(repo, "log", "-1", "--format=%s")))
        if name == "refresh":
            (repo / lr.FILES[0]).write_text("new\n", encoding="utf-8")
        return SimpleNamespace(returncode=1 if name == fail else 0, stdout=MOVED if name == "refresh" else "",
                               stderr="")

    return run


def test_it_refreshes_checks_commits_then_installs_fresh_on_linux_and_windows(checkout, monkeypatch):
    ran = []
    monkeypatch.setattr(lr, "execute", fake(checkout, ran))
    lr.cmd_lock_refresh(SimpleNamespace(task="lock"))
    assert [n for n, _ in ran] == ["refresh", "check", "admin pages", "fresh install linux", "fresh install windows"]
    subject = "The core's lock refreshed to the latest: 2 package(s) moved"
    # The fresh installs run on the commit: fresh.py's bundle holds committed code only
    assert dict(ran)["check"] == "main" and dict(ran)["fresh install linux"] == subject
    body = sh(checkout, "log", "-1", "--format=%b")
    assert "- cryptography: 47.0.0 → 50.0.2" in body and "- numpy: 2.4.4 → 2.5.5" in body
    assert not sh(checkout, "status", "--porcelain")


def test_a_failed_step_stops_it_and_says_how_to_hold_a_package_back(checkout, monkeypatch):
    ran = []
    monkeypatch.setattr(lr, "execute", fake(checkout, ran, fail="check"))
    with pytest.raises(hw.Stop, match="constraint-dependencies"):
        lr.cmd_lock_refresh(SimpleNamespace(task="lock"))
    assert [n for n, _ in ran] == ["refresh", "check"]
    assert sh(checkout, "log", "-1", "--format=%s") == "main"  # nothing committed


def test_it_runs_only_in_a_task_that_reserves_the_core(checkout):
    hw.save(hw.Task(id="other", title="other", env=5, repos=["homehiro"], state="working"))
    with pytest.raises(hw.Stop, match="doesn't reserve hiroleague"):
        lr.cmd_lock_refresh(SimpleNamespace(task="other"))


def test_nothing_moved_says_so() -> None:
    assert lr.moved("uv.lock refreshed to the latest: 0 package(s) changed.\n") == []
    assert lr.commit_message([]) == "The core's lock refreshed to the latest: nothing moved\n"
