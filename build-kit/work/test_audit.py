"""hiro-work audit: a run's start and report as Work events, read back from the same log."""

import json
import subprocess
from datetime import datetime, timedelta

import pytest

import audit
import hiro_work as hw


@pytest.fixture
def log(tmp_path, monkeypatch):
    """A log of its own (a test's events never reach the sender), and a state file beside it."""
    monkeypatch.setattr(hw, "LOGS", tmp_path / "logs")
    monkeypatch.setattr(hw, "EVENTS", tmp_path / "logs" / "events.jsonl")
    monkeypatch.setattr(audit, "STATE", tmp_path / "doc-audit-state.json")
    return tmp_path


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def repo_with(tmp_path, name, commits):
    """A repo whose recorded commit is followed by *commits* more on main."""
    r = tmp_path / name
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    git(r, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "recorded")
    recorded = subprocess.run(["git", "rev-parse", "HEAD"], cwd=r, capture_output=True, text=True).stdout.strip()
    for i in range(commits):
        git(r, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", f"c{i}")
    return {"path": str(r), "branch": "main", "commit": recorded}


def at(minutes_ago: float) -> str:
    return (datetime.now().astimezone() - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")


def test_a_run_is_running_until_its_report_and_stopped_when_a_newer_one_begins_or_it_is_too_old():
    lines = [
        {"at": at(3000), "step": "audit", "phase": "start", "run": "old", "repos": []},
        {"at": at(200), "step": "audit", "phase": "start", "run": "a", "repos": [{"repo": "x", "commits": 2}]},
        {"at": at(190), "step": "audit", "phase": "end", "run": "a", "report": "# A"},
        {"at": at(100), "step": "audit", "phase": "start", "run": "b", "repos": []},
        {"at": at(5), "step": "audit", "phase": "start", "run": "c", "repos": []},
        {"at": at(5), "step": "servers up", "phase": "end"},  # another step: not a run
    ]
    runs = audit.runs(lines)
    assert [(r["id"], r["state"]) for r in runs] == [("c", "running"), ("b", "stopped"), ("a", "reported"),
                                                    ("old", "stopped")]
    assert runs[2]["report"] == "# A" and runs[2]["repos"] == [{"repo": "x", "commits": 2}]


def test_only_repos_with_new_commits_since_the_last_run_unless_full_or_one_repo(tmp_path):
    state = {"repos": {"core": repo_with(tmp_path, "core", 3), "app": repo_with(tmp_path, "app", 0)}}
    assert audit.new_commits(state, "since the last run") == [{"repo": "core", "commits": 3}]
    assert audit.new_commits(state, "full") == [{"repo": "core", "commits": 3}, {"repo": "app", "commits": 0}]
    assert audit.new_commits(state, "app") == [{"repo": "app", "commits": 0}]


def test_start_then_report_records_the_run_and_hiro_work_reads_it_back(log, capsys):
    audit.STATE.write_text(json.dumps({"repos": {"core": repo_with(log, "core", 2)}}), encoding="utf-8")
    assert hw.main(["audit", "start"]) == 0
    [start] = [json.loads(x) for x in hw.EVENTS.read_text(encoding="utf-8").splitlines()]
    assert start["step"] == "audit" and start["phase"] == "start" and start["repos"] == [{"repo": "core", "commits": 2}]
    rid = start["run"]

    assert hw.main(["audit", "latest"]) == 1  # nothing reported yet
    report = log / "report.md"
    report.write_text("# Doc audit\n\n| a | b |\n|---|---|\n| x | <ul><li>y</li></ul> |\n", encoding="utf-8")
    assert hw.main(["audit", "report", rid, str(report)]) == 0
    assert hw.main(["audit", "report", rid, str(report)]) == 1  # a run is a snapshot: one report
    capsys.readouterr()

    assert hw.main(["audit", "latest"]) == 0
    out = capsys.readouterr().out
    assert f"Audit run {rid}" in out and "core (2)" in out and "| x | <ul><li>y</li></ul> |" in out
    assert hw.main(["audit", rid]) == 0 and "# Doc audit" in capsys.readouterr().out
    assert hw.main(["audit", "list"]) == 0 and "reported" in capsys.readouterr().out


def test_a_report_too_long_for_one_event_is_refused(log, monkeypatch):
    hw.event(step="audit", phase="start", run="r", repos=[])
    report = log / "big.md"
    report.write_text("x" * (audit.MAX_REPORT + 1), encoding="utf-8")
    assert hw.main(["audit", "report", "r", str(report)]) == 1
    assert len(hw.EVENTS.read_text(encoding="utf-8").splitlines()) == 1  # nothing written


def test_times_read_as_the_day_and_a_12_hour_clock():
    now = datetime.now().astimezone()
    assert audit.when(now.replace(hour=13, minute=5).isoformat()) == "Today, 1:05 PM"
    assert audit.when(None) == "—"
