"""Landing and dropping a plan that ships whole (the plan "Plan branches", phase 3; its cases by letter): plan land,
the landing's merge, plan close setting the branch aside, a send taking it back, and what reopen, resume, the sweep and
the deploy make of it. Real git in tmp_path, on test_plan_branches.py's world."""

import json
import subprocess

import pytest

import deploy
import hiro_work as hw
import plan
import test_plan_branches
from test_plan_branches import DOC, at, commit, env0, events, free, holds, on_main, sh, start, tip

world = test_plan_branches.world  # the fixture, shared with phase 2's tests


def send_phases(w, *phases, name="Chores") -> int:
    """The plan sent as shipping whole, with these phases: (name, state, tasks)."""
    body = {"name": name, "doc": DOC, "ships": "whole",
            "phases": [{"name": n, "state": s, "tasks": list(t)} for n, s, t in phases]}
    f = w.root / "plan.json"
    f.write_text(json.dumps(body), encoding="utf-8")
    return hw.main(["plan", "send", str(f)])


def states() -> dict[str, str]:
    return {ph["name"]: ph["state"] for ph in plan.latest("Chores")["phases"]}


def merged_phase(w, tid="p1", file=None, text=None, repos="codehiro"):
    """A phase that starts, commits one file and merges into the plan's branch."""
    assert start(tid, repos) == 0
    commit(w, hw.get(tid).env, file or f"{tid}.txt", text or tid, repos.split(",")[0])
    assert hw.main(["merge", tid]) == 0


def land(*more) -> int:
    return hw.main(["plan", "land", "Chores", *more])


def parents(w, ref, repo="codehiro") -> list[str]:
    return sh(env0(w, repo), "rev-list", "--parents", "-n", "1", ref).split()[1:]


# ---------------------------------------------------------------------------------------- D6. a phase's state


def test_d6_a_phase_merged_into_its_plan_is_in_the_plan(world):
    send_phases(world, ("One", "working", ["p1"]), ("Two", "next", []))
    merged_phase(world)
    assert states() == {"One": "inplan", "Two": "next"}


def test_d6_a_phase_another_open_task_works_on_keeps_its_state(world):
    send_phases(world, ("One", "working", ["p1", "p2"]))
    assert start("p2") == 0
    merged_phase(world)
    assert states() == {"One": "working"}


# ------------------------------------------------------------------------------------------------- F. landing


def test_f1_land_starts_a_task_from_main_that_merges_the_plans_branch_as_one_merge(world):
    send_phases(world, ("One", "working", ["p1"]))
    merged_phase(world, repos="codehiro,nethiro")
    held, main = tip(world, "plan/chores"), tip(world, "main")
    assert land() == 0
    t = hw.get("land-chores")
    assert (t.target, t.lands, t.part_of, t.repos) == ("", "plan/chores", "Chores", ["codehiro"])
    assert t.landed == {"codehiro": held}
    assert parents(world, "task/land-chores") == [main, held]  # main first: git revert -m 1 backs it out
    assert sh(env0(world), "log", "-1", "--format=%s", "task/land-chores") == "Land Chores"
    starts = [e for e in events(world) if e["step"] == "task" and e["phase"] == "start" and e["task"] == "land-chores"]
    assert starts[0]["lands"] == "plan/chores"


def test_f2_nothing_to_land_is_refused(world, capsys):
    send_phases(world, ("One", "working", ["p1"]))
    assert start("p1") == 0  # the branch exists, holding only main
    assert land() == 1
    assert "nothing to land" in capsys.readouterr().out
    assert not hw.task_path("land-chores").exists()


def test_f2_a_plan_that_ships_phase_by_phase_has_nothing_to_land(world, capsys):
    body = {"name": "Chores", "doc": DOC, "phases": [{"name": "One", "state": "working"}]}
    (world.root / "p.json").write_text(json.dumps(body), encoding="utf-8")
    hw.main(["plan", "send", str(world.root / "p.json")])
    assert land() == 1
    assert "phase by phase" in capsys.readouterr().out


def test_f3_a_second_landing_while_one_is_open_is_refused(world, capsys):
    send_phases(world, ("One", "working", ["p1"]))
    merged_phase(world)
    assert land() == 0
    capsys.readouterr()
    assert land() == 1
    assert "land-chores" in capsys.readouterr().out


def test_f4_open_phases_are_named_and_their_work_isnt_in_the_landing(world, capsys):
    send_phases(world, ("One", "working", ["p1"]), ("Two", "working", ["p2"]))
    merged_phase(world)
    assert start("p2") == 0
    commit(world, hw.get("p2").env, "p2.txt", "p2")
    capsys.readouterr()
    assert land() == 0
    assert "p2" in capsys.readouterr().out
    assert holds(world, "task/land-chores", "p1.txt") == "p1"
    assert holds(world, "task/land-chores", "p2.txt") is None


def test_f5_a_conflict_with_main_stops_the_landing_and_a_resolve_lets_it_merge(world, capsys):
    send_phases(world, ("One", "working", ["p1"]))
    merged_phase(world, file="base.txt", text="plan\n")
    on_main(world, "codehiro", "base.txt", "main\n")
    capsys.readouterr()
    assert land() == 1
    out = capsys.readouterr().out
    assert "conflicts with main" in out and "hiro-work merge land-chores" in out
    t = hw.get("land-chores")
    d = at(world, t.env)
    assert sh(d, "status", "--porcelain") == ""  # the merge was undone: the folder is clean
    assert hw.main(["merge", "land-chores"]) == 1  # its branch doesn't hold the plan yet
    held = t.landed["codehiro"]
    subprocess.run(["git", "-C", str(d), "merge", "--no-ff", "-m", "Land Chores", held], capture_output=True)
    (d / "base.txt").write_text("plan and main\n", encoding="utf-8")
    sh(d, "add", "base.txt")
    sh(d, "commit", "-q", "--no-edit")
    assert hw.main(["merge", "land-chores"]) == 0
    assert holds(world, "main", "base.txt") == "plan and main\n"


def test_f6_the_landings_merge_brings_it_onto_main_and_the_plans_branch_goes(world):
    send_phases(world, ("One", "working", ["p1"]), ("Two", "next", []))
    merged_phase(world)
    assert states()["One"] == "inplan"
    land()
    landing = tip(world, "task/land-chores")
    assert hw.main(["merge", "land-chores"]) == 0
    assert tip(world, "main") == landing and holds(world, "main", "p1.txt") == "p1"
    assert not tip(world, "plan/chores")  # main holds all of it
    assert states() == {"One": "merged", "Two": "next"}
    recs = [e for e in events(world) if e["step"] == "commits" and e["task"] == "land-chores"]
    assert [r["how"] for r in recs] == ["land"]
    end = [e for e in events(world) if e["step"] == "task" and e["phase"] == "end"][-1]
    assert (end["task"], end["lands"], end["plan"], end["merged"]) == ("land-chores", "plan/chores", "Chores", True)
    assert free(world, hw.json.loads((hw.TASKS / "done" / "land-chores.json").read_text("utf-8"))["env"])


def test_f6_a_kit_change_in_the_plan_checks_the_apps_at_its_landing(world, monkeypatch):
    monkeypatch.setattr(hw, "KIT_PATHS", ["kit.txt"])
    send_phases(world, ("One", "working", ["p1"]))
    merged_phase(world, file="kit.txt", text="kit", repos="hiroleague")
    land()
    hw.main(["merge", "land-chores"])
    checked = [repos for tid, repos in world.checks if tid == "land-chores"][-1]
    assert set(checked) >= {"codehiro", "nethiro"}  # the apps beside the plan's kit change (hiroleague has no check.sh here)


def test_f7_a_phase_merged_during_the_landing_keeps_the_branch_and_lands_next_time(world):
    send_phases(world, ("One", "working", ["p1"]), ("Two", "working", ["p2"]))
    merged_phase(world)
    land()
    merged_phase(world, "p2")  # into the plan while the landing waits
    assert hw.main(["merge", "land-chores"]) == 0
    assert holds(world, "main", "p1.txt") == "p1" and holds(world, "main", "p2.txt") is None
    assert holds(world, "plan/chores", "p2.txt") == "p2"
    assert states() == {"One": "merged", "Two": "inplan"}
    assert land() == 0 and hw.main(["merge", "land-chores"]) == 0
    assert holds(world, "main", "p2.txt") == "p2" and not tip(world, "plan/chores")


def test_f8_a_cancelled_landing_leaves_the_plan_and_main_as_they_were(world):
    send_phases(world, ("One", "working", ["p1"]))
    merged_phase(world)
    held, main = tip(world, "plan/chores"), tip(world, "main")
    land()
    assert hw.main(["cancel", "land-chores"]) == 0
    assert (tip(world, "plan/chores"), tip(world, "main")) == (held, main)
    assert states() == {"One": "inplan"}
    assert land() == 0  # it can land again


def test_f9_after_a_landing_the_next_phase_starts_from_main_and_the_branch_is_made_again(world):
    send_phases(world, ("One", "working", ["p1"]), ("Two", "next", ["p2"]))
    merged_phase(world)
    land()
    hw.main(["merge", "land-chores"])
    assert start("p2") == 0
    assert tip(world, "plan/chores") == tip(world, "main") == tip(world, "task/p2")
    assert holds(world, "task/p2", "p1.txt") == "p1"


def test_f10_a_landed_plan_backs_out_as_one_revert(world):
    send_phases(world, ("One", "working", ["p1", "p2"]))
    before = tip(world, "main")
    merged_phase(world)
    merged_phase(world, "p2")
    land()
    hw.main(["merge", "land-chores"])
    d = env0(world)
    sh(d, "revert", "--no-edit", "-m", "1", "HEAD")
    assert sh(d, "diff", before, "HEAD") == ""


def test_f11_a_failed_check_at_the_landing_moves_nothing(world, capsys):
    send_phases(world, ("One", "working", ["p1"]))
    merged_phase(world)
    land()
    held, main = tip(world, "plan/chores"), tip(world, "main")
    world.failing = ["codehiro (log)"]
    assert hw.main(["merge", "land-chores"]) == 1
    assert (tip(world, "plan/chores"), tip(world, "main")) == (held, main)
    assert hw.get("land-chores").state == "working"
    world.failing = []
    assert hw.main(["merge", "land-chores"]) == 0


def test_f12_the_deploy_names_each_plan_not_landed(world):
    send_phases(world, ("One", "working", ["p1"]))
    assert plan.unlanded() == []
    merged_phase(world, repos="codehiro")
    assert plan.unlanded() == ["Chores (plan/chores: codehiro)"]
    lines = []

    class Nothing:
        push, first, then = [], [], []

    deploy.show_open(lines.append, Nothing())
    assert any("Plans not landed" in x and "Chores" in x for x in lines)
    land()
    hw.main(["merge", "land-chores"])
    assert plan.unlanded() == []


# --------------------------------------------------------------------------------- G. dropping, taking back


def test_g1_closing_a_plan_sets_its_branch_aside_and_cancels_its_phases(world):
    send_phases(world, ("One", "working", ["p1"]), ("Two", "working", ["p2"]), ("Three", "todo", []))
    merged_phase(world, repos="codehiro")
    assert start("p2", "codehiro,nethiro") == 0  # nethiro's branch: made from main, nothing in it
    held, main = tip(world, "plan/chores"), tip(world, "main")
    assert hw.main(["plan", "close", "Chores"]) == 0
    assert states() == {"One": "cancelled", "Two": "cancelled", "Three": "cancelled"}
    assert hw.task_path("p2").exists() is False
    assert not tip(world, "plan/chores") and tip(world, "cancelled/plan/chores") == held
    assert not tip(world, "plan/chores", "nethiro") and not tip(world, "cancelled/plan/chores", "nethiro")
    assert tip(world, "main") == main  # main never saw it


def test_g2_closing_after_a_partial_landing_keeps_what_landed(world):
    send_phases(world, ("One", "working", ["p1"]), ("Two", "working", ["p2"]))
    merged_phase(world)
    land()
    hw.main(["merge", "land-chores"])
    merged_phase(world, "p2")
    assert hw.main(["plan", "close", "Chores"]) == 0
    assert states() == {"One": "merged", "Two": "cancelled"}
    assert holds(world, "main", "p1.txt") == "p1" and holds(world, "main", "p2.txt") is None
    assert holds(world, "cancelled/plan/chores", "p2.txt") == "p2"


def test_g3_a_send_that_opens_the_plan_again_takes_its_branch_back(world):
    send_phases(world, ("One", "working", ["p1"]), ("Two", "next", ["p2"]))
    merged_phase(world)
    held = tip(world, "plan/chores")
    hw.main(["start", "p2", "--repos", "codehiro", "--part-of", "Chores"])
    hw.main(["plan", "close", "Chores"])
    assert hw.main(["reopen", "p2"]) == 1  # E7: its plan is closed
    send_phases(world, ("One", "inplan", ["p1"]), ("Two", "working", ["p2"]))
    assert tip(world, "plan/chores") == held and not tip(world, "cancelled/plan/chores")
    assert hw.main(["reopen", "p2"]) == 0
    assert hw.get("p2").target == "plan/chores"


def test_g6_a_renamed_plan_leaves_its_old_branch_for_the_sweep(world, capsys):
    send_phases(world, ("One", "working", ["p1"]))
    merged_phase(world)
    send_phases(world, ("One", "inplan", ["p1"]), name="Chores board")
    plan.resend(plan.latest("Chores"), [{**ph, "state": "cancelled"} for ph in plan.latest("Chores")["phases"]])
    capsys.readouterr()
    hw.main(["sweep"])
    assert "plan/chores: no open plan" in capsys.readouterr().out


# ----------------------------------------------------------------------------------- E. resume, reopen


def test_e3_resume_after_the_plan_landed_makes_the_branch_again_at_its_merge(world):
    send_phases(world, ("One", "working", ["p1"]), ("Two", "working", ["p2"]))
    merged_phase(world)
    assert start("p2") == 0
    commit(world, hw.get("p2").env, "p2.txt", "p2")
    hw.main(["pause", "p2"])
    land()
    hw.main(["merge", "land-chores"])
    assert not tip(world, "plan/chores")
    assert hw.main(["resume", "p2"]) == 0
    assert hw.main(["merge", "p2"]) == 0
    assert holds(world, "plan/chores", "p2.txt") == "p2" and holds(world, "plan/chores", "p1.txt") == "p1"
    assert holds(world, "main", "p2.txt") is None


# ---------------------------------------------------------------------------------------------- I. the sweep


def test_i2_an_open_plans_branch_isnt_left_behind_but_a_checkout_on_one_is(world, capsys):
    send_phases(world, ("One", "working", ["p1"]))
    assert start("p1") == 0  # the branch holds only main: --merged would list it
    capsys.readouterr()
    hw.main(["sweep"])
    out = capsys.readouterr().out
    assert "plan/chores" not in out
    sh(at(world, 3), "switch", "-q", "plan/chores")
    hw.main(["sweep"])
    assert "has plan/chores checked out" in capsys.readouterr().out


@pytest.mark.parametrize("listing,keep,left", [
    ("  plan/chores\n  task/x\n* main\n", ("plan/chores",), ["task/x"]),
    ("  plan/chores\n", (), ["plan/chores"]),
])
def test_i2_merged_left_keeps_an_open_plans_branch(listing, keep, left):
    assert hw.merged_left(listing, "main", keep) == left
