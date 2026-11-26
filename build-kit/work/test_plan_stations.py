"""A plan phase follows its tasks through the stations by itself: start (--phase), review, merge, the landing and the
deploy each send the plan again with the phase moved, forward only, and only the task's own phase. Real git in
tmp_path, on test_plan_branches.py's world."""

import json

import pytest

import hiro_work as hw
import plan
import test_plan_branches
from test_plan_branches import DOC, commit, env0, events, sh, start, tip

world = test_plan_branches.world  # the fixture, shared with the plan-branch tests


def send(w, *phases, name="Chores", ships="phases") -> int:
    """The plan sent with these phases: (name, state, tasks)."""
    body = {"name": name, "doc": DOC, "phases": [{"name": n, "state": s, "tasks": list(t)} for n, s, t in phases]}
    if ships == "whole":
        body["ships"] = "whole"
    f = w.root / "plan.json"
    f.write_text(json.dumps(body), encoding="utf-8")
    return hw.main(["plan", "send", str(f)])


def phases(name="Chores") -> dict[str, tuple[str, list[str]]]:
    return {ph["name"]: (ph["state"], ph["tasks"]) for ph in plan.latest(name)["phases"]}


def merged_task(tid: str, state: str = "done", merged_at: dict | None = None) -> None:
    """A task record as hiro-work leaves it: open, merged (with where its merge left each repo) or cancelled."""
    t = hw.Task(id=tid, title=tid, env=None, repos=["codehiro"], state=state, merged_at=merged_at)
    hw.TASKS.mkdir(parents=True, exist_ok=True)
    hw.save(t)


# ------------------------------------------------------------------------------------------------- start


def test_start_with_phase_joins_it_and_moves_it_to_working(world, capsys):
    send(world, ("Mockup", "live", ["m"]), ("Tick", "todo", []), ("Points", "todo", []))
    capsys.readouterr()
    assert start("tick", "codehiro", "Chores", "--phase", "tick") == 0  # the phase's name in any case
    assert phases() == {"Mockup": ("live", ["m"]), "Tick": ("working", ["tick"]), "Points": ("todo", [])}
    out = capsys.readouterr().out
    assert out.count("Plan Chores:") == 1 and "phase 2 (Tick) now Being worked on in CodeHiro" in out


@pytest.mark.parametrize("state", ["next", "waits"])
def test_a_phase_not_started_moves_to_working_from_next_or_waits(world, state):
    send(world, ("Tick", state, []))
    assert start("tick", "codehiro", "Chores", "--phase", "Tick") == 0
    assert phases()["Tick"] == ("working", ["tick"])


def test_start_without_phase_moves_a_phase_a_send_named_it_in_and_leaves_the_rest(world):
    send(world, ("Tick", "next", ["tick"]), ("Points", "todo", []))
    assert start("tick") == 0
    assert phases() == {"Tick": ("working", ["tick"]), "Points": ("todo", [])}
    before = len([e for e in events(world) if e["step"] == plan.STEP])
    assert start("other", "nethiro", "") == 0  # no phase names it: nothing sent
    assert len([e for e in events(world) if e["step"] == plan.STEP]) == before


@pytest.mark.parametrize("phase, words", [
    ("Nope", 'Plan Chores has no phase Nope. Its phases: "Mockup"; "Tick"'),
    ("Mockup", "phase 1 (Mockup) is Merged, so a new task can't join it"),
])
def test_a_phase_that_isnt_there_or_is_done_stops_the_start_before_any_reserve(world, capsys, phase, words):
    send(world, ("Mockup", "merged", ["m"]), ("Tick", "todo", []))
    assert start("tick", "codehiro", "Chores", "--phase", phase) == 1
    assert words in capsys.readouterr().out
    assert not (hw.TASKS / "tick.json").exists() and not tip(world, "task/tick")


def test_phase_with_no_plan_sent_or_no_part_of_stops_the_start(world, capsys):
    assert start("tick", "codehiro", "Chores", "--phase", "Tick") == 1
    assert "No plan Chores has been sent" in capsys.readouterr().out
    assert start("tick", "codehiro", "", "--phase", "Tick") == 1
    assert "--phase needs --part-of" in capsys.readouterr().out
    assert not (hw.TASKS / "tick.json").exists()
    assert not [e for e in events(world) if e["step"] == plan.STEP]  # nothing moves for a plan with no send


def test_a_phase_another_open_task_works_on_takes_the_new_task_and_keeps_its_state(world, capsys):
    send(world, ("Tick", "review", ["first"]))
    merged_task("first", state="paused")
    capsys.readouterr()
    assert start("second", "codehiro", "Chores", "--phase", "Tick") == 0
    assert phases()["Tick"] == ("review", ["first", "second"])
    assert "second joins phase 1 (Tick) in CodeHiro; it stays In review" in capsys.readouterr().out


# ----------------------------------------------------------------------------------------------- review


def test_review_moves_working_to_review_and_never_a_phase_further_on(world, capsys):
    send(world, ("Tick", "todo", []), ("Done", "merged", ["tick"]))
    start("tick", "codehiro", "Chores", "--phase", "Tick")
    capsys.readouterr()
    assert hw.main(["review", "tick"]) == 0
    assert phases() == {"Tick": ("review", ["tick"]), "Done": ("merged", ["tick"])}  # merged stays merged
    assert "phase 1 (Tick) now In review in CodeHiro" in capsys.readouterr().out


def test_review_keeps_a_phase_another_open_task_works_on(world):
    send(world, ("Tick", "working", ["tick", "helper"]))
    merged_task("helper", state="paused")
    start("tick")
    assert hw.main(["review", "tick"]) == 0
    assert phases()["Tick"] == ("working", ["tick", "helper"])


# ----------------------------------------------------------------------------------------------- merge


def test_a_merge_into_main_moves_the_phase_to_merged_and_records_where_it_left_each_repo(world, capsys):
    send(world, ("Tick", "todo", []), ("Old", "live", ["tick"]))
    start("tick", "codehiro,nethiro", "Chores", "--phase", "Tick")
    hw.main(["review", "tick"])
    commit(world, 1, "tick.txt", "tick")
    capsys.readouterr()
    assert hw.main(["merge", "tick"]) == 0
    assert phases() == {"Tick": ("merged", ["tick"]), "Old": ("live", ["tick"])}  # live never moves back
    assert "phase 1 (Tick) now Merged in CodeHiro" in capsys.readouterr().out
    done = json.loads((hw.TASKS / "done" / "tick.json").read_text(encoding="utf-8"))
    assert done["merged_at"] == {"codehiro": tip(world, "main")}  # nethiro brought nothing: not named


def test_a_merge_keeps_a_phase_another_open_task_works_on(world):
    send(world, ("Tick", "working", ["tick", "helper"]))
    merged_task("helper", state="paused")
    start("tick")
    commit(world, 1, "tick.txt", "tick")
    assert hw.main(["merge", "tick"]) == 0
    assert phases()["Tick"] == ("working", ["tick", "helper"])


def test_a_merge_with_no_plan_sent_sends_nothing(world):
    start("tick", "codehiro", "Chores")
    commit(world, 1, "tick.txt", "tick")
    assert hw.main(["merge", "tick"]) == 0
    assert not [e for e in events(world) if e["step"] == plan.STEP]


# ------------------------------------------------------------------- a plan that ships whole: inplan, landing, live


def test_a_whole_plans_phase_goes_working_inplan_merged_then_live(world):
    send(world, ("One", "todo", []), ships="whole")
    assert start("p1", "codehiro", "Chores", "--phase", "One") == 0
    assert phases()["One"] == ("working", ["p1"])
    commit(world, 1, "p1.txt", "p1")
    hw.main(["merge", "p1"])
    assert phases()["One"] == ("inplan", ["p1"])
    at = json.loads((hw.TASKS / "done" / "p1.json").read_text(encoding="utf-8"))["merged_at"]
    assert at == {"codehiro": tip(world, "plan/chores")}
    assert plan.went_live({"codehiro": tip(world, "main")}, {"codehiro"}) == []  # held in the plan: main lacks it
    assert hw.main(["plan", "land", "Chores"]) == 0
    assert hw.main(["merge", "land-chores"]) == 0
    assert phases()["One"] == ("merged", ["p1"])
    [line] = plan.went_live({"codehiro": tip(world, "main")}, {"codehiro"})
    assert "phase 1 (One) now Live in CodeHiro" in line
    assert phases()["One"] == ("live", ["p1"])


# ------------------------------------------------------------------------------------------------ deploy


@pytest.fixture
def shipped(world):
    """A phase merged into main: its task's work is the tip of env0's codehiro main."""
    d = env0(world)
    (d / "w.txt").write_text("w", encoding="utf-8")
    sh(d, "add", "w.txt")
    sh(d, "commit", "-q", "-m", "work")
    return tip(world, "main")


def test_the_deploy_moves_a_merged_phase_to_live_once_its_work_runs_live(world, shipped):
    merged_task("tick", merged_at={"codehiro": shipped})
    send(world, ("Tick", "merged", ["tick"]), ("Later", "merged", ["later"]))
    merged_task("later", state="working")
    [line] = plan.went_live({"codehiro": shipped}, {"codehiro"})
    assert line.startswith("Plan Chores: phase 1 (Tick) now Live in CodeHiro")
    assert phases() == {"Tick": ("live", ["tick"]), "Later": ("merged", ["later"])}  # an open task: not yet


@pytest.mark.parametrize("why", ["repo not live", "head lacks it", "old record", "no record", "only cancelled"])
def test_the_deploy_leaves_a_merged_phase_when_its_work_isnt_surely_live(world, shipped, why):
    before = sh(env0(world), "rev-parse", "main~1")
    tasks = ["tick"]
    if why == "old record":
        merged_task("tick", merged_at=None)  # merged before hiro-work kept where
    elif why == "only cancelled":
        merged_task("tick", state="cancelled")
    elif why != "no record":
        merged_task("tick", merged_at={"codehiro": shipped})
    send(world, ("Tick", "merged", tasks))
    heads = {"codehiro": before if why == "head lacks it" else shipped}
    live = set() if why == "repo not live" else {"codehiro"}
    assert plan.went_live(heads, live) == []
    assert phases()["Tick"] == ("merged", ["tick"])


def test_a_cancelled_task_beside_a_merged_one_doesnt_hold_the_phase(world, shipped):
    merged_task("gave-up", state="cancelled")
    merged_task("tick", merged_at={"codehiro": shipped})
    send(world, ("Tick", "merged", ["gave-up", "tick"]))
    assert plan.went_live({"codehiro": shipped}, {"codehiro"})
    assert phases()["Tick"][0] == "live"


def test_the_deploy_moves_only_merged_phases(world, shipped):
    merged_task("tick", merged_at={"codehiro": shipped})
    send(world, ("A", "check", ["tick"]), ("B", "inplan", ["tick"]), ("C", "review", ["tick"]))
    assert plan.went_live({"codehiro": shipped}, {"codehiro"}) == []
    assert [s for s, _ in phases().values()] == ["check", "inplan", "review"]
