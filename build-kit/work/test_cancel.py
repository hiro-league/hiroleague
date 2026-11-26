"""Cancelling and reopening a task, and closing a plan: what each does to the task, its branches and its plan."""

import json
import subprocess

import pytest

import hiro_work as hw

PLAN = {
    "name": "Chores board",
    "doc": "https://claude.ai/artifact/LQVoaS4SrcvmowbGxiHi3g",
    "phases": [
        {"name": "Mockup", "state": "live", "tasks": ["chores-mockup"]},
        {"name": "Tick them off", "state": "working", "tasks": ["chores-tick"]},
        {"name": "Points", "state": "todo"},
    ],
}


def sh(d, *args) -> str:
    return subprocess.run(["git", "-C", str(d), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def work(tmp_path, monkeypatch):
    """A codehiro repo of its own (main, plus a task's branch), a tasks folder and a log, and no servers."""
    repo = tmp_path / "codehiro"
    repo.mkdir()
    sh(repo, "init", "-q", "-b", "main")
    sh(repo, "config", "user.email", "t@t")
    sh(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("a", encoding="utf-8")
    sh(repo, "add", "a.txt")
    sh(repo, "commit", "-q", "-m", "main")
    monkeypatch.setattr(hw, "repo_dir", lambda env, r: repo)
    monkeypatch.setattr(hw, "TASKS", tmp_path / "tasks")
    monkeypatch.setattr(hw, "LOGS", tmp_path / "logs")
    monkeypatch.setattr(hw, "EVENTS", tmp_path / "logs" / "events.jsonl")
    monkeypatch.setattr(hw, "servers_down", lambda env: None)
    return repo


def task(repo, tid: str, state: str = "paused", env: int | None = None, commit: bool = True, part_of: str = ""):
    sh(repo, "branch", f"task/{tid}", "main")
    if commit:
        sh(repo, "switch", "-q", f"task/{tid}")
        (repo / f"{tid}.txt").write_text(tid, encoding="utf-8")
        sh(repo, "add", f"{tid}.txt")
        sh(repo, "commit", "-q", "-m", tid)
    sh(repo, "switch", "-q", "main") if state == "paused" or not env else sh(repo, "switch", "-q", f"task/{tid}")
    t = hw.Task(id=tid, title=tid, env=env, repos=["codehiro"], state=state, part_of=part_of)
    hw.TASKS.mkdir(parents=True, exist_ok=True)
    hw.save(t)
    return t


def events() -> list[dict]:
    return [json.loads(x) for x in hw.EVENTS.read_text(encoding="utf-8").splitlines()] if hw.EVENTS.exists() else []


def send(tmp_path, body, *more) -> int:
    f = tmp_path / "plan.json"
    f.write_text(json.dumps(body), encoding="utf-8")
    return hw.main(["plan", "send", str(f), *more])


def last_plan() -> dict:
    return [e for e in events() if e["step"] == "plan-sent"][-1]


def test_a_cancelled_task_keeps_its_work_on_a_cancelled_branch_and_ends_unmerged(work, capsys):
    task(work, "t")
    assert hw.main(["cancel", "t"]) == 0
    assert sh(work, "branch", "--list", "cancelled/t") and not sh(work, "branch", "--list", "task/t")
    assert json.loads((hw.TASKS / "done" / "t.json").read_text(encoding="utf-8"))["state"] == "cancelled"
    assert not (hw.TASKS / "t.json").exists()
    end = events()[-1]
    assert (end["step"], end["phase"], end["merged"], end["cancelled"]) == ("task", "end", False, True)
    assert "hiro-work reopen t" in capsys.readouterr().out


def test_a_working_task_with_no_commits_leaves_no_branch_and_its_environment_free(work):
    task(work, "t", state="working", env=3, commit=False)
    assert hw.main(["cancel", "t"]) == 0
    assert not sh(work, "branch", "--list", "task/t", "cancelled/t")
    assert sh(work, "branch", "--show-current") == ""  # detached on main, as a free environment is


def test_uncommitted_files_stop_a_cancel_before_anything_moves(work, capsys):
    task(work, "t", state="working", env=3)
    (work / "loose.txt").write_text("x", encoding="utf-8")
    assert hw.main(["cancel", "t"]) == 1
    assert "uncommitted files" in capsys.readouterr().out
    assert (hw.TASKS / "t.json").exists() and sh(work, "branch", "--list", "task/t")


def test_reopen_takes_the_branch_back_and_resumes_and_a_merged_task_cant(work, monkeypatch, capsys):
    resumed = []
    monkeypatch.setattr(hw, "cmd_resume", lambda a: resumed.append((a.task, a.env)))
    task(work, "t")
    hw.main(["cancel", "t"])
    assert hw.main(["reopen", "t", "--env", "4"]) == 0
    assert sh(work, "branch", "--list", "task/t") and not sh(work, "branch", "--list", "cancelled/t")
    assert json.loads((hw.TASKS / "t.json").read_text(encoding="utf-8"))["state"] == "paused"
    assert not (hw.TASKS / "done" / "t.json").exists()
    assert resumed == [("t", 4)]
    assert any(e["step"] == "reopened" for e in events())
    merged = hw.Task(id="m", title="m", env=None, repos=["codehiro"], state="done")
    hw.save(merged)
    assert hw.main(["reopen", "m"]) == 1
    assert "was merged" in capsys.readouterr().out


def test_a_cancelled_subtask_puts_its_phase_back_to_next_and_the_plan_goes_on(work, tmp_path, capsys):
    send(tmp_path, PLAN)
    task(work, "chores-tick", part_of="Chores board")
    assert hw.main(["cancel", "chores-tick"]) == 0
    states = [p["state"] for p in last_plan()["phases"]]
    assert states == ["live", "next", "todo"]
    assert "now Next in CodeHiro (the plan doc's states catch up when the plan ends)" in capsys.readouterr().out


def test_a_phase_another_open_task_works_on_keeps_its_state(work, tmp_path):
    two = json.loads(json.dumps(PLAN))
    two["phases"][1]["tasks"] = ["chores-tick", "chores-tick-2"]
    send(tmp_path, two)
    task(work, "chores-tick")
    task(work, "chores-tick-2", state="paused")
    hw.main(["cancel", "chores-tick"])
    assert last_plan()["phases"][1]["state"] == "working"


def test_pause_and_resume_move_the_phase_to_paused_and_back(work, tmp_path, monkeypatch):
    import plan

    send(tmp_path, PLAN)
    assert plan.follow("chores-tick", "paused", ("working", "review"), set())
    assert last_plan()["phases"][1]["state"] == "paused"
    assert plan.follow("chores-tick", "working", ("paused",), set())
    assert last_plan()["phases"][1]["state"] == "working"
    assert plan.follow("someone-else", "paused", ("working",), set()) == []  # no phase names it: nothing sent


def test_closing_a_plan_cancels_its_open_tasks_and_unfinished_phases_and_keeps_the_live_ones(work, tmp_path, capsys):
    send(tmp_path, PLAN)
    task(work, "chores-tick", part_of="Chores board")
    assert hw.main(["plan", "close", "Chores board"]) == 0
    assert [p["state"] for p in last_plan()["phases"]] == ["live", "cancelled", "cancelled"]
    assert json.loads((hw.TASKS / "done" / "chores-tick.json").read_text(encoding="utf-8"))["state"] == "cancelled"
    assert "1 live, 2 cancelled" in capsys.readouterr().out


def test_a_send_cant_drop_a_finished_or_worked_on_phase_unless_named(work, tmp_path, capsys):
    send(tmp_path, PLAN)
    capsys.readouterr()
    renamed = json.loads(json.dumps(PLAN))
    renamed["phases"][0]["name"] = "Mockup of the board"
    del renamed["phases"][1]
    assert send(tmp_path, renamed) == 1
    out = capsys.readouterr().out
    assert '"Mockup" (live' in out and '"Tick them off" (working, tasks chores-tick)' in out
    assert len([e for e in events() if e["step"] == "plan-sent"]) == 1  # nothing written
    assert send(tmp_path, renamed, "--remove", "Mockup", "--remove", "tick them off") == 0
    dropped = json.loads(json.dumps(PLAN))
    dropped["phases"].pop()  # a phase not started, with no tasks: free to go
    assert send(tmp_path, dropped | {"phases": renamed["phases"]}) == 0
