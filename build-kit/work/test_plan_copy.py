"""A plan's branch copied off the PC (the plan "Plan branches", phase 7): each move puts it on the repo's bare repo on
Simone (the `server` remote), a landing and a close follow it there, and a copy that fails is a note, never a stop.
A bare repo in tmp_path stands for Simone's, on test_plan_branches.py's world."""

import json

import pytest

import hiro_work as hw
import test_plan_branches
from test_plan_branches import DOC, commit, env0, events, sh, start, tip

world = test_plan_branches.world  # the fixture, shared with phase 2's tests


@pytest.fixture
def simone(world):
    """A bare repo per env0 repo, as each one's `server` remote."""
    for repo in hw.REPOS:
        bare = world.root / "simone" / f"{repo}.git"
        bare.mkdir(parents=True)
        sh(bare, "init", "-q", "--bare")
        sh(env0(world, repo), "remote", "add", "server", str(bare))
    return world


def on_simone(w, branch, repo="codehiro") -> str:
    return sh(w.root / "simone" / f"{repo}.git", "rev-parse", "--verify", "-q", f"refs/heads/{branch}", check=False)


def send(w, *states, name="Chores"):
    body = {"name": name, "doc": DOC, "ships": "whole",
            "phases": [{"name": f"P{i}", "state": s, "tasks": [f"p{i}"]} for i, s in enumerate(states, 1)]}
    (w.root / "plan.json").write_text(json.dumps(body), encoding="utf-8")
    assert hw.main(["plan", "send", str(w.root / "plan.json")]) == 0


def phase(w, tid="p1"):
    assert start(tid) == 0
    commit(w, hw.get(tid).env, f"{tid}.txt", tid)
    assert hw.main(["merge", tid]) == 0


def test_a_phase_merge_copies_the_plans_branch_to_simone(simone):
    send(simone, "working")
    phase(simone)
    assert on_simone(simone, "plan/chores") == tip(simone, "plan/chores")
    assert not on_simone(simone, "main")  # only the plan's branch: main goes there by the deploy


def test_each_later_move_is_copied_too(simone):
    send(simone, "working", "working")
    phase(simone)
    phase(simone, "p2")
    assert on_simone(simone, "plan/chores") == tip(simone, "plan/chores")


def test_a_landing_removes_the_copy_with_the_branch(simone):
    send(simone, "working")
    phase(simone)
    assert hw.main(["plan", "land", "Chores"]) == 0
    assert hw.main(["merge", "land-chores"]) == 0
    assert not tip(simone, "plan/chores") and not on_simone(simone, "plan/chores")


def test_a_close_moves_the_copy_aside_and_a_reopening_send_brings_it_back(simone):
    send(simone, "working", "next")
    phase(simone)
    held = tip(simone, "plan/chores")
    assert hw.main(["plan", "close", "Chores"]) == 0
    assert not on_simone(simone, "plan/chores") and on_simone(simone, "cancelled/plan/chores") == held
    send(simone, "inplan", "working")
    assert on_simone(simone, "plan/chores") == held and not on_simone(simone, "cancelled/plan/chores")


def test_with_simone_away_the_merge_still_goes_and_says_so(world, capsys):
    send(world, "working")
    phase(world)  # no `server` remote: the copy fails
    assert tip(world, "plan/chores")
    assert "not copied to Simone" in capsys.readouterr().out
    failed = [e for e in events(world) if e.get("step") == "copy off" and e.get("phase") == "end"]
    assert failed and failed[-1]["ok"] is False


def test_the_copy_ignores_a_commit_hooks_git_variables(simone, monkeypatch):
    send(simone, "working")
    assert start("p1") == 0
    commit(simone, hw.get("p1").env, "p1.txt", "p1")
    # As a commit's hook runs: git's variables name the committing repo, which a push would read instead
    monkeypatch.setenv("GIT_DIR", str(env0(simone, "nethiro") / ".git"))
    monkeypatch.setenv("GIT_INDEX_FILE", str(env0(simone, "nethiro") / ".git" / "index"))
    assert hw.copy_off("codehiro", "main") is None
    monkeypatch.delenv("GIT_DIR")
    monkeypatch.delenv("GIT_INDEX_FILE")
    assert on_simone(simone, "main") == tip(simone, "main") and not on_simone(simone, "main", "nethiro")


def test_removing_a_copy_that_isnt_there_is_no_failure(simone):
    assert hw.copy_off("codehiro", "plan/never", delete=True) is None
