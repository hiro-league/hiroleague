"""A plan that ships whole: its branch plan/<name>, and how start, reserve, sync, merge, pause, resume, cancel, reopen
and the commit hook follow it (the plan "Plan branches", phase 2; its cases by letter). Real git in tmp_path: env0's
repos on main, env1 to env3 as their detached worktrees, as hiro-work makes them."""

import dataclasses
import json
import subprocess

import pytest

import hiro_work as hw
import plan

DOC = "https://claude.ai/artifact/LQVoaS4SrcvmowbGxiHi3g"
LINES = "one\ntwo\nthree\n"


def sh(d, *args, check=True) -> str:
    return subprocess.run(["git", "-C", str(d), *args], check=check, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def world(tmp_path, monkeypatch):
    """env0's hiroleague, codehiro and nethiro on main, each with env1 to env3 as worktrees; tasks, a log, and no
    servers, installs, data copies or checks (check_repos answers from ``world.failing``)."""
    for who in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{who}_NAME", "t")
        monkeypatch.setenv(f"GIT_{who}_EMAIL", "t@t")
    monkeypatch.setattr(hw, "ROOT", tmp_path)
    monkeypatch.setattr(hw, "TASKS", tmp_path / "tasks")
    monkeypatch.setattr(hw, "LOGS", tmp_path / "logs")
    monkeypatch.setattr(hw, "EVENTS", tmp_path / "logs" / "events.jsonl")
    monkeypatch.setattr(hw, "REPOS", ["hiroleague", "codehiro", "nethiro"])
    monkeypatch.setattr(hw, "MAIN", {})
    monkeypatch.setattr(hw, "KIT_READERS", ["codehiro", "nethiro"])
    for repo in hw.REPOS:
        d = tmp_path / "env0" / repo
        d.mkdir(parents=True)
        sh(d, "init", "-q", "-b", "main")
        (d / "base.txt").write_text(LINES, encoding="utf-8")
        sh(d, "add", "base.txt")
        sh(d, "commit", "-q", "-m", "start")
        for env in (1, 2, 3):
            sh(d, "worktree", "add", "-q", "--detach", str(tmp_path / f"env{env}" / repo), "main")
    installs: list[tuple[int, str]] = []
    checks: list[tuple[str, list[str]]] = []

    class World:
        root = tmp_path
        failing: list[str] = []
        during_check = None  # a function run while a merge checks (two phases merging at once)

    def check_repos(task, env, repos):
        checks.append((task.id, list(repos)))
        if World.during_check:
            hook, World.during_check = World.during_check, None
            hook()
        return list(World.failing)

    monkeypatch.setattr(hw, "init_env", lambda env, task=None, install=True: None)
    monkeypatch.setattr(hw, "fetch_all", lambda repos, task, env: None)
    monkeypatch.setattr(hw, "install_all", lambda env, repos, task=None: None)
    monkeypatch.setattr(hw, "install", lambda env, repo, task=None, force=False, spare_servers=False:
                        installs.append((env, repo)) or [])
    monkeypatch.setattr(hw, "refresh_data", lambda env, task=None, source="env0": None)
    monkeypatch.setattr(hw, "servers_down", lambda env, names=None: None)
    monkeypatch.setattr(hw, "check_repos", check_repos)
    World.installs, World.checks = installs, checks
    return World


def env0(w, repo="codehiro"):
    return w.root / "env0" / repo


def at(w, env, repo="codehiro"):
    return w.root / f"env{env}" / repo


def send(w, name="Chores", ships="whole", *more) -> int:
    body = {"name": name, "doc": DOC, "phases": [{"name": "One", "state": "working"}]}
    if ships:
        body["ships"] = ships
    f = w.root / "plan.json"
    f.write_text(json.dumps(body), encoding="utf-8")
    return hw.main(["plan", "send", str(f), *more])


def start(tid, repos="codehiro", part_of="Chores", *more) -> int:
    return hw.main(["start", tid, "--repos", repos, *(["--part-of", part_of] if part_of else []), *more])


def commit(w, env, file, text, repo="codehiro"):
    d = at(w, env, repo)
    (d / file).write_text(text, encoding="utf-8")
    sh(d, "add", file)
    sh(d, "commit", "-q", "-m", f"{file}: {text.strip()[:20]}")


def on_main(w, repo, file, text):
    """A task merged into env0's main meanwhile (a fix, another plan's landing)."""
    d = env0(w, repo)
    (d / file).write_text(text, encoding="utf-8")
    sh(d, "add", file)
    sh(d, "commit", "-q", "-m", f"main: {file}")


def tip(w, ref, repo="codehiro") -> str:
    return sh(env0(w, repo), "rev-parse", "--verify", "-q", ref, check=False)


def holds(w, ref, file, repo="codehiro") -> str | None:
    out = subprocess.run(["git", "-C", str(env0(w, repo)), "show", f"{ref}:{file}"], capture_output=True, text=True)
    return out.stdout if out.returncode == 0 else None


def events(w) -> list[dict]:
    path = w.root / "logs" / "events.jsonl"
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def free(w, env) -> bool:
    """Every repo of the environment sits detached on main, as a free environment's do."""
    return all(sh(at(w, env, r), "branch", "--show-current") == "" and
               sh(at(w, env, r), "rev-parse", "HEAD") == tip(w, "main", r) for r in hw.REPOS)


# ------------------------------------------------------------------------------------------- A. nothing changes


def test_a1_a_plan_that_ships_phase_by_phase_merges_into_main_as_before(world):
    assert send(world, ships="") == 0
    assert start("p1") == 0
    t = hw.get("p1")
    assert (t.target, t.plan) == ("", "")
    assert not tip(world, "plan/chores")  # no branch for a plan that ships phase by phase
    commit(world, 1, "p1.txt", "p1")
    assert hw.main(["merge", "p1"]) == 0
    assert holds(world, "main", "p1.txt") == "p1"  # env0's main moved, as always
    end = [e for e in events(world) if e["step"] == "task" and e["phase"] == "end"][-1]
    assert "into" not in end


def test_a2_a_record_from_before_has_no_target_and_reads_as_main(world):
    hw.TASKS.mkdir(parents=True, exist_ok=True)
    (hw.TASKS / "old.json").write_text('{"id": "old", "title": "old", "env": 1, "repos": ["codehiro"]}',
                                       encoding="utf-8")
    t = hw.get("old")
    assert (t.target, t.plan) == ("", "")
    assert hw.follow_ref(t, "nethiro") == "main"


def test_a3_an_older_hiro_work_reads_a_task_with_a_target_and_keeps_it(world, monkeypatch):
    hw.TASKS.mkdir(parents=True, exist_ok=True)
    (hw.TASKS / "p.json").write_text(json.dumps({"id": "p", "title": "p", "env": 1, "repos": ["codehiro"],
                                                 "target": "plan/chores", "plan": "Chores"}), encoding="utf-8")
    fields = [(f.name, f.type, f) for f in dataclasses.fields(hw.Task) if f.name not in ("target", "plan")]
    older = dataclasses.make_dataclass("Task", fields)  # the Task of a hiro-work from before this change
    monkeypatch.setattr(hw, "Task", older)
    t = hw.get("p")
    t.title = "renamed"
    hw.save(t)
    saved = json.loads((hw.TASKS / "p.json").read_text(encoding="utf-8"))
    assert (saved["target"], saved["plan"], saved["title"]) == ("plan/chores", "Chores", "renamed")


# ------------------------------------------------------------------------------------------- B. starting a phase


def test_b1_the_first_phase_makes_the_plans_branch_from_main_and_starts_from_it(world):
    send(world)
    assert start("p1") == 0
    t = hw.get("p1")
    assert (t.target, t.plan, t.part_of) == ("plan/chores", "Chores", "Chores")
    assert tip(world, "plan/chores") == tip(world, "main")  # made from main
    assert sh(at(world, 1), "branch", "--show-current") == "task/p1"
    assert t.base["codehiro"] == tip(world, "plan/chores")
    assert not tip(world, "plan/chores", "hiroleague")  # only where the task reserves


def test_b2_a_second_phase_beside_an_open_one_starts_with_no_stop_in_its_own_environment(world):
    send(world)
    start("p1")
    assert start("p2") == 0  # no --own-branch
    assert (hw.get("p1").env, hw.get("p2").env) == (1, 2)


def test_b3_a_phase_after_others_merged_holds_their_work(world):
    send(world)
    start("p1")
    commit(world, 1, "p1.txt", "p1")
    assert hw.main(["merge", "p1"]) == 0
    start("p2")
    assert (at(world, 1) / "p1.txt").read_text(encoding="utf-8") == "p1"  # env1 is free again: p2 took it


def test_b4_a_repo_the_plan_hasnt_touched_gets_the_branch_from_main_and_the_others_keep_theirs(world):
    send(world)
    start("p1")
    commit(world, 1, "p1.txt", "p1")
    hw.main(["merge", "p1"])
    held = tip(world, "plan/chores")
    assert start("p2", "hiroleague,codehiro") == 0
    assert tip(world, "plan/chores", "hiroleague") == tip(world, "main", "hiroleague")
    assert tip(world, "plan/chores") == held  # codehiro's kept its work
    assert hw.get("p2").base == {"hiroleague": tip(world, "main", "hiroleague"), "codehiro": held}


def test_b5_the_repos_a_task_doesnt_reserve_follow_the_plans_branch_where_it_has_one_and_main_elsewhere(world):
    send(world)
    start("p1")
    commit(world, 1, "p1.txt", "p1")
    hw.main(["merge", "p1"])
    assert start("p2", "hiroleague") == 0
    env = hw.get("p2").env
    assert sh(at(world, env), "rev-parse", "HEAD") == tip(world, "plan/chores")
    assert sh(at(world, env), "branch", "--show-current") == ""  # detached: never checked out
    assert sh(at(world, env, "nethiro"), "rev-parse", "HEAD") == tip(world, "main", "nethiro")


def test_b6_a_plans_branch_behind_main_is_brought_up_before_the_tasks_branch_starts(world):
    send(world)
    start("p1")
    commit(world, 1, "p1.txt", "p1")
    hw.main(["merge", "p1"])
    on_main(world, "codehiro", "fix.txt", "fix")
    assert start("p2") == 0
    for ref in ("plan/chores", "task/p2"):
        assert holds(world, ref, "fix.txt") == "fix" and holds(world, ref, "p1.txt") == "p1"
    assert hw.get("p2").base["codehiro"] == tip(world, "plan/chores")


def test_b7_a_plans_branch_that_conflicts_with_main_is_left_and_the_first_sync_asks_to_resolve(world, capsys):
    send(world)
    start("p1")
    commit(world, 1, "base.txt", "one\nPLAN\nthree\n")
    hw.main(["merge", "p1"])
    held = tip(world, "plan/chores")
    on_main(world, "codehiro", "base.txt", "one\nMAIN\nthree\n")
    capsys.readouterr()
    assert start("p2") == 0
    assert "plan/chores conflicts with main" in capsys.readouterr().out
    assert tip(world, "plan/chores") == held
    assert hw.main(["sync", "p2"]) == 1
    assert "conflicts" in capsys.readouterr().out


def test_b8_on_main_targets_main_though_the_plan_ships_whole(world):
    send(world)
    start("p1")
    commit(world, 1, "p1.txt", "p1")
    hw.main(["merge", "p1"])
    assert start("fix", "codehiro", "Chores", "--on-main") == 0
    t = hw.get("fix")
    assert (t.target, t.base["codehiro"]) == ("", tip(world, "main"))
    assert not (at(world, t.env) / "p1.txt").exists()


def test_b9_a_plan_branch_for_a_plan_not_shipping_whole_stops_the_start_before_any_reserve(world, capsys):
    send(world, ships="")
    sh(env0(world), "branch", "plan/chores", "main")
    assert start("p1") == 1
    assert "plan/chores" in capsys.readouterr().out
    assert not hw.task_path("p1").exists()


def test_b10_part_of_a_task_on_a_plans_branch_takes_its_plan_and_target(world):
    send(world)
    start("p1")
    assert start("p2", "codehiro", "p1") == 0
    t = hw.get("p2")
    assert (t.target, t.plan, t.part_of) == ("plan/chores", "Chores", "Chores")


def test_b11_reserve_starts_the_added_repo_from_the_plans_branch_made_from_main_if_missing(world):
    send(world)
    start("p1")
    assert hw.main(["reserve", "p1", "hiroleague"]) == 0
    t = hw.get("p1")
    assert tip(world, "plan/chores", "hiroleague") == tip(world, "main", "hiroleague")
    assert t.base["hiroleague"] == tip(world, "plan/chores", "hiroleague")
    assert sh(at(world, 1, "hiroleague"), "branch", "--show-current") == "task/p1"


def test_b12_a_plan_shipping_phase_by_phase_names_own_branch_for_a_phase_and_joining_for_a_step(world, capsys):
    send(world, ships="")
    start("p1")
    capsys.readouterr()
    assert start("p2") == 1
    out = capsys.readouterr().out
    assert "--own-branch" in out and "guard.py join" in out and "phase" in out and "step" in out


# ----------------------------------------------------------------------------------------------- C. working


def test_c1_the_commit_hook_moves_each_clean_repo_up_to_the_plans_branch_and_names_a_dirty_one(world):
    send(world)
    start("p1")
    start("p2", "hiroleague")
    commit(world, 1, "p1.txt", "p1")
    hw.main(["merge", "p1"])  # the plan's branch moved past env2's codehiro
    (at(world, 2, "nethiro") / "loose.txt").write_text("x", encoding="utf-8")
    notes = hw.bring_up_others(2, hw.get("p2"))
    assert sh(at(world, 2), "rev-parse", "HEAD") == tip(world, "plan/chores")
    assert any(n.startswith("nethiro: has uncommitted files") for n in notes)
    hw.cmd_fresh(type("A", (), {"path": str(at(world, 2, "hiroleague"))})())  # the hook itself runs it


def test_c2_sync_merges_githubs_main_env0s_main_then_the_plans_branch_and_a_conflict_names_all_three(world, capsys):
    send(world)
    start("p1")
    start("p2")
    commit(world, 1, "p1.txt", "p1")
    hw.main(["merge", "p1"])
    on_main(world, "codehiro", "fix.txt", "fix")
    commit(world, 2, "p2.txt", "p2")
    assert hw.main(["sync", "p2"]) == 0
    merged = sh(at(world, 2), "log", "--first-parent", "--format=%s", "-2").splitlines()
    assert "plan/chores" in merged[0] and "'main'" in merged[1]  # main first, the plan's branch after
    # A conflict with the plan's branch names all three and says to sync again
    commit(world, 2, "base.txt", "one\nP2\nthree\n")
    start("p3")
    commit(world, 1, "base.txt", "one\nP3\nthree\n")
    hw.main(["merge", "p3"])
    capsys.readouterr()
    assert hw.main(["sync", "p2"]) == 1
    out = capsys.readouterr().out
    assert "origin/main, main and plan/chores" in out and "sync again" in out


def test_c3_two_phases_on_different_lines_of_one_file_merge_with_no_conflict(world):
    send(world)
    start("p1")
    start("p2")
    commit(world, 1, "base.txt", "ONE\ntwo\nthree\n")
    commit(world, 2, "base.txt", "one\ntwo\nTHREE\n")
    assert hw.main(["merge", "p1"]) == 0
    assert hw.main(["merge", "p2"]) == 0
    assert holds(world, "plan/chores", "base.txt") == "ONE\ntwo\nTHREE\n"
    assert holds(world, "main", "base.txt") == LINES  # main never saw it


def test_c4_two_phases_on_the_same_lines_stop_the_second_until_it_resolves_and_commits(world, capsys):
    send(world)
    start("p1")
    start("p2")
    commit(world, 1, "base.txt", "one\nP1\nthree\n")
    commit(world, 2, "base.txt", "one\nP2\nthree\n")
    hw.main(["merge", "p1"])
    held = tip(world, "plan/chores")
    assert hw.main(["merge", "p2"]) == 1
    assert "conflicts" in capsys.readouterr().out
    assert tip(world, "plan/chores") == held  # nothing moved
    d = at(world, 2)
    sh(d, "merge", "-q", "main")
    sh(d, "merge", "-q", "plan/chores", check=False)
    (d / "base.txt").write_text("one\nP1 and P2\nthree\n", encoding="utf-8")
    sh(d, "add", "base.txt")
    sh(d, "commit", "-q", "--no-edit")
    assert hw.main(["merge", "p2"]) == 0
    assert holds(world, "plan/chores", "base.txt") == "one\nP1 and P2\nthree\n"


def test_c5_after_a_kit_phase_merges_an_app_phases_core_sits_on_the_plans_branch(world):
    send(world)
    start("kit", "hiroleague")
    start("app", "codehiro")
    (at(world, 1, "hiroleague") / "build-kit").mkdir()
    commit(world, 1, "build-kit/kit.txt", "kit", repo="hiroleague")
    assert hw.main(["merge", "kit"]) == 0
    hw.cmd_fresh(type("A", (), {"path": str(at(world, 2))})())  # the app phase's next commit
    assert sh(at(world, 2, "hiroleague"), "rev-parse", "HEAD") == tip(world, "plan/chores", "hiroleague")
    assert (at(world, 2, "hiroleague") / "build-kit" / "kit.txt").exists()


def test_c6_a_fix_on_main_reaches_each_phase_at_its_sync_and_an_unreserved_plan_branch_when_clean(world):
    send(world)
    start("p1")
    commit(world, 1, "p1.txt", "p1")
    hw.main(["merge", "p1"])  # codehiro's plan branch holds work; no open phase reserves codehiro now
    start("p2", "hiroleague")
    on_main(world, "codehiro", "fix.txt", "fix")
    on_main(world, "hiroleague", "fix.txt", "fix")
    assert hw.main(["sync", "p2"]) == 0
    assert holds(world, "task/p2", "fix.txt", "hiroleague") == "fix"  # the phase takes it at its sync
    assert holds(world, "plan/chores", "fix.txt") == "fix"  # the plan branch no phase reserves, merged cleanly
    assert sh(at(world, hw.get("p2").env), "rev-parse", "HEAD") == tip(world, "plan/chores")


# ------------------------------------------------------------------------------------- D. merging into the plan


def test_d1_a_phase_merges_into_the_plans_branch_and_main_never_moves(world):
    send(world)
    start("p1", "hiroleague,codehiro")
    commit(world, 1, "p1.txt", "p1")
    main, work = tip(world, "main"), tip(world, "task/p1")
    assert hw.main(["merge", "p1"]) == 0
    assert tip(world, "plan/chores") == work and not tip(world, "task/p1")
    assert tip(world, "main") == main and sh(env0(world), "rev-parse", "HEAD") == main
    assert [i for i in world.installs if i[0] == 0] == []  # nothing waits in env0
    assert free(world, 1)  # every repo released on main
    assert hw.leftovers(1, hw.load_tasks()) == []  # I3
    assert json.loads((hw.TASKS / "done" / "p1.json").read_text(encoding="utf-8"))["state"] == "done"
    end = [e for e in events(world) if e["step"] == "task" and e["phase"] == "end"][-1]
    assert (end["merged"], end["into"], end["plan"]) == (True, "plan/chores", "Chores")


def test_d2_its_commits_are_recorded_as_brought_into_the_plan(world):
    send(world)
    start("p1")
    commit(world, 1, "p1.txt", "p1")
    work = sh(at(world, 1), "rev-parse", "HEAD")
    hw.main(["merge", "p1"])
    [rec] = [e for e in events(world) if e["step"] == "commits"]
    assert (rec["how"], rec["repo"], rec["commits"]) == ("plan", "codehiro", [work])


def test_d3_two_phases_merging_at_once_the_second_is_told_to_merge_again_and_nothing_is_lost(world, capsys):
    send(world)
    start("p1")
    start("p2")
    commit(world, 1, "p1.txt", "p1")
    commit(world, 2, "p2.txt", "p2")
    world.during_check = lambda: hw.main(["merge", "p1"])  # p1 merges while p2's checks run
    assert hw.main(["merge", "p2"]) == 1
    assert "merge again" in capsys.readouterr().out
    assert hw.get("p2").state == "working" and holds(world, "plan/chores", "p2.txt") is None
    assert hw.main(["merge", "p2"]) == 0
    assert holds(world, "plan/chores", "p1.txt") == "p1" and holds(world, "plan/chores", "p2.txt") == "p2"


def test_d4_a_checkout_on_the_plans_branch_stops_the_merge_and_is_named(world, capsys):
    send(world)
    start("p1")
    commit(world, 1, "p1.txt", "p1")
    sh(at(world, 3), "switch", "-q", "plan/chores")  # someone checked it out by hand
    held = tip(world, "plan/chores")
    assert hw.main(["merge", "p1"]) == 1
    assert "env3" in capsys.readouterr().out
    assert tip(world, "plan/chores") == held and hw.get("p1").state == "working"


def test_d5_a_failed_check_moves_nothing(world, capsys):
    send(world)
    start("p1")
    commit(world, 1, "p1.txt", "p1")
    held = tip(world, "plan/chores")
    world.failing = ["codehiro (log)"]
    assert hw.main(["merge", "p1"]) == 1
    assert "Checks failed" in capsys.readouterr().out
    assert tip(world, "plan/chores") == held and hw.get("p1").state == "working"


# ------------------------------------------------------------------------------ E. pause, resume, cancel, reopen


def test_e1_e2_pause_frees_every_repo_on_main_and_resume_follows_the_plans_branch_again(world):
    send(world)
    start("p1")
    commit(world, 1, "p1.txt", "p1")
    hw.main(["merge", "p1"])
    start("p2", "hiroleague")
    env = hw.get("p2").env
    (at(world, env, "hiroleague") / "draft.txt").write_text("draft", encoding="utf-8")
    assert hw.main(["pause", "p2"]) == 0
    assert free(world, env) and hw.leftovers(env, hw.load_tasks()) == []  # I3
    assert holds(world, "task/p2", "draft.txt", "hiroleague") == "draft"  # saved on its branch
    assert hw.main(["resume", "p2", "--env", "3"]) == 0
    assert sh(at(world, 3, "hiroleague"), "branch", "--show-current") == "task/p2"
    assert (at(world, 3, "hiroleague") / "draft.txt").exists()
    assert sh(at(world, 3), "rev-parse", "HEAD") == tip(world, "plan/chores")
    assert sh(at(world, 3, "nethiro"), "rev-parse", "HEAD") == tip(world, "main", "nethiro")


def test_e4_e5_cancel_counts_a_tasks_own_commits_against_the_plans_branch(world, capsys):
    send(world)
    start("p1")
    commit(world, 1, "p1.txt", "p1")
    hw.main(["merge", "p1"])  # the plan's branch now holds work main lacks
    start("mine")
    start("none")
    commit(world, hw.get("mine").env, "mine.txt", "mine")
    envs = hw.get("mine").env, hw.get("none").env
    assert hw.main(["cancel", "mine"]) == 0
    assert tip(world, "cancelled/mine") and not tip(world, "task/mine")
    assert hw.main(["cancel", "none"]) == 0
    assert not tip(world, "cancelled/none") and not tip(world, "task/none")  # the plan's commits aren't its own
    assert all(free(world, e) for e in envs)  # I3


def test_e6_reopen_takes_the_branch_back_or_starts_again_from_the_plans_branch(world):
    send(world)
    start("p1")
    commit(world, 1, "p1.txt", "p1")
    hw.main(["merge", "p1"])
    start("mine")
    start("none")
    commit(world, hw.get("mine").env, "mine.txt", "mine")
    hw.main(["cancel", "mine"])
    hw.main(["cancel", "none"])
    assert hw.main(["reopen", "mine"]) == 0
    assert holds(world, "task/mine", "mine.txt") == "mine" and not tip(world, "cancelled/mine")
    assert hw.main(["reopen", "none"]) == 0
    assert tip(world, "task/none") == tip(world, "plan/chores")


# ------------------------------------------------------------------------------------------------ G. the send


def test_a_send_names_the_plans_branch_and_reads_ships(world):
    assert plan.branch_name("Logging & tracing!") == "plan/logging-tracing"
    send(world, "Chores board")
    assert plan.branch_of("chores board") == "plan/chores-board"
    assert plan.latest("Chores board")["ships"] == "whole"
    send(world, "Other", ships="")
    assert plan.branch_of("Other") == "" and plan.latest("Other")["ships"] == "phases"
    assert send(world, "Third", ships="sometimes") == 1
    # A pause or cancel sends the plan again: it keeps its branch
    plan.resend(plan.latest("Chores board"), plan.latest("Chores board")["phases"])
    assert plan.branch_of("Chores board") == "plan/chores-board"


def test_g4_turning_ships_whole_off_is_refused_while_the_branch_holds_work(world, capsys):
    send(world)
    start("p1")
    assert send(world, ships="") == 1  # an open phase works on the branch
    commit(world, 1, "p1.txt", "p1")
    hw.main(["merge", "p1"])
    capsys.readouterr()
    assert send(world, ships="") == 1
    assert "land it or close it" in capsys.readouterr().out
    assert plan.branch_of("Chores") == "plan/chores"


def test_g4_a_branch_that_holds_nothing_goes_when_ships_whole_is_turned_off(world):
    send(world)
    start("p1")
    hw.main(["cancel", "p1"])  # no work of its own: the branch is main's commit
    assert tip(world, "plan/chores")
    assert send(world, ships="") == 0
    assert not tip(world, "plan/chores") and plan.branch_of("Chores") == ""


def test_g5_two_plans_whose_names_give_one_branch_name_are_refused(world, capsys):
    assert send(world, "Chores board") == 0
    assert send(world, "chores-board!") == 1
    assert "plan/chores-board" in capsys.readouterr().out
    assert send(world, "chores-board!", ships="") == 0  # phase by phase: no branch to share


# ----------------------------------------------------------------------------------------- H. several plans


def test_h1_two_plans_on_one_repo_have_two_branches_and_neither_holds_the_others_work(world):
    send(world, "Plan A")
    send(world, "Plan B")
    start("a1", "codehiro", "Plan A")
    start("b1", "codehiro", "Plan B")
    commit(world, 1, "a.txt", "a")
    commit(world, 2, "b.txt", "b")
    assert hw.main(["merge", "a1"]) == 0 and hw.main(["merge", "b1"]) == 0
    assert holds(world, "plan/plan-a", "a.txt") == "a" and holds(world, "plan/plan-a", "b.txt") is None
    assert holds(world, "plan/plan-b", "b.txt") == "b" and holds(world, "plan/plan-b", "a.txt") is None


def test_h4_an_environment_holds_one_task_so_its_repos_follow_that_tasks_plan(world, capsys):
    send(world, "Plan A")
    send(world, "Plan B")
    start("a1", "codehiro", "Plan A")
    assert start("b1", "hiroleague", "Plan B", "--env", "1") == 1
    assert "env1 is busy" in capsys.readouterr().out


# -------------------------------------------------------------------------------------------- I. looking


def test_i1_status_and_the_work_card_name_the_target_beside_the_branch(world, capsys, monkeypatch):
    monkeypatch.setattr(hw, "listening", lambda port: False)  # the PC's own servers are no part of this
    send(world)
    start("p1")
    assert "branch task/p1, into plan/chores |" in capsys.readouterr().out
    hw.main(["status"])
    assert "p1 (codehiro, into plan/chores)" in capsys.readouterr().out


def test_i4_a_reserved_repo_counts_as_changed_from_the_plans_branch_at_its_start(world):
    send(world)
    start("p1")
    commit(world, 1, "p1.txt", "p1")
    hw.main(["merge", "p1"])
    start("p2")
    env = hw.get("p2").env
    assert hw.changed_repos(env, hw.load_tasks()) == []  # it starts with p1's work, which isn't its own
    commit(world, env, "p2.txt", "p2")
    assert hw.changed_repos(env, hw.load_tasks()) == ["codehiro"]
