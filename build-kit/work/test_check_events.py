"""check_events.py: a check part's start and end become Work events of the task that claims the repo there."""

import json
import threading

import pytest

import check_events as ce
import ship


@pytest.fixture
def hiro(tmp_path, monkeypatch):
    """A C:\\hiro of the test's own: one working task in env1 claiming codehiro, and its events log."""
    monkeypatch.setattr(ce, "ROOT", tmp_path)
    monkeypatch.setattr(ce, "TASKS", tmp_path / "tasks")
    monkeypatch.setattr(ship, "EVENTS", tmp_path / "logs" / "events.jsonl")
    monkeypatch.setattr(ship, "kick", lambda *a, **k: None)
    (tmp_path / "tasks").mkdir()
    (tmp_path / "tasks" / "t.json").write_text(
        json.dumps({"id": "t", "state": "working", "env": 1, "repos": ["hiroleague", "codehiro"]}), encoding="utf-8"
    )
    (tmp_path / "env1" / "codehiro").mkdir(parents=True)
    return tmp_path


def events(hiro):
    return [json.loads(x) for x in (hiro / "logs" / "events.jsonl").read_text(encoding="utf-8").splitlines()]


def test_a_part_starts_and_ends_inside_the_repos_check(hiro):
    folder = str(hiro / "env1" / "codehiro")
    ce.main([folder, "start", "dashboard: npm run check"])
    ce.main([folder, "end", "dashboard: npm run check", "0", "27"])
    start, end = events(hiro)
    assert start == {**start, "task": "t", "env": 1, "repo": "codehiro", "step": "dashboard: npm run check",
                     "parent": "check", "phase": "start"}
    assert (end["ok"], end["seconds"], "error" in end) == (True, 27.0, False)


def test_a_failed_part_carries_the_end_of_its_output(hiro, tmp_path):
    out = tmp_path / "part.log"
    out.write_text("\n".join(f"line {i}" for i in range(120)), encoding="utf-8")
    ce.main([str(hiro / "env1" / "codehiro"), "end", "service: tests", "1", "38", str(out)])
    end = events(hiro)[0]
    assert (end["ok"], end["error"]) == (False, "exit 1")
    assert end["tail"].splitlines()[0] == "line 20"


def test_git_bash_paths_and_checks_with_no_task(hiro):
    posix = "/" + str(hiro).replace("\\", "/").replace(":", "", 1)
    assert ce.where(posix + "/env1/codehiro") == (1, "codehiro")
    assert ce.task_of(2, "codehiro") is None


def test_outside_hiro_nothing_is_written(hiro, tmp_path_factory):
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    assert ce.main([str(elsewhere), "start", "x"]) == 0
    assert not (hiro / "logs" / "events.jsonl").exists()


def test_appends_side_by_side_stay_whole_lines(tmp_path):
    log = tmp_path / "events.jsonl"

    def write(n):
        for i in range(100):
            ship.append(log, {"writer": n, "i": i, "pad": "x" * 500})

    threads = [threading.Thread(target=write, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    lines = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 400


def test_tests_are_counted_from_what_the_runners_print():
    out = "\n".join([
        "........ [ 10%]",  # pytest -q, with xdist too
        "..F.s [ 20%]",
        "All checks passed!",  # a linter: no tests
        " ✓ src/a.test.ts (12 tests) 4ms",  # vitest
        " ❯ src/b.test.ts (3 tests | 1 failed) 2ms",
        "tests/test_a.py::test_one PASSED  [ 1%]",  # pytest -v
        "...",  # unittest, still writing its line
    ])
    assert ce.count_tests(out) == 32
    assert ce.count_tests("ruff: 0 errors\nbuilt in 3.1s") == 0


def test_progress_sends_the_count_only_when_it_changed(hiro, tmp_path):
    folder, out = str(hiro / "env1" / "codehiro"), tmp_path / "part.log"
    out.write_text("collecting...\n", encoding="utf-8")
    ce.main([folder, "progress", "service: tests", str(out)])  # no tests yet: nothing
    out.write_text(".....", encoding="utf-8")
    ce.main([folder, "progress", "service: tests", str(out)])
    ce.main([folder, "progress", "service: tests", str(out)])  # the same count: nothing
    out.write_text("..........\n", encoding="utf-8")
    ce.main([folder, "progress", "service: tests", str(out)])
    ce.main([folder, "end", "service: tests", "0", "9", str(out)])
    got = events(hiro)
    assert [(e["phase"], e.get("tests")) for e in got] == [("progress", 5), ("progress", 10), ("end", 10)]
    assert got[0] == {**got[0], "task": "t", "step": "service: tests", "parent": "check"}
