"""The deploy's choices: what lacks what, what stops it, the order (the core first, the rest side by side)."""

from datetime import datetime

import pytest

import hiro_work as hw
import deploy as tr


def facts(repo, github=(), live=(), **kw):
    return tr.Facts(repo=repo, head="h", github_lacks=list(github), live_lacks=list(live), **kw)


def test_the_core_deploys_alone_first_and_the_apps_and_aicam_side_by_side_after_it():
    plan = tr.make_plan([facts("hiroleague", live=["a"]), facts("homehiro", live=["b"]), facts("aicam", live=["c"]),
                         facts("nethiro")])
    assert plan.first == ["hiroleague"]
    assert plan.then == ["homehiro", "aicam"]
    assert plan.deploys == ["hiroleague", "homehiro", "aicam"]


def test_without_a_core_change_the_apps_go_first_and_together():
    plan = tr.make_plan([facts("hiroleague"), facts("homehiro", live=["b"]), facts("nethiro", live=["c"])])
    assert plan.first == []
    assert plan.then == ["homehiro", "nethiro"]


def test_github_gets_every_repo_it_lacks_commits_of_and_hiro_docs_goes_to_simone_beside_the_apps():
    plan = tr.make_plan([facts("homehiro", github=["a"], live=["a"]), facts("hiro-docs", github=["d"], live=["d"]),
                         facts("nethiro", live=["n"])])
    assert plan.push == ["homehiro", "hiro-docs"]
    assert plan.deploys == ["homehiro", "hiro-docs", "nethiro"]


def test_hiro_docs_has_no_deploy_hook_so_the_push_itself_is_its_deploy():
    assert tr.DEPLOY["hiro-docs"] in tr.NO_HOOK and tr.DEPLOY["aicam"] in tr.NO_HOOK
    assert tr.DEPLOY["codehiro"] not in tr.NO_HOOK


def test_a_repo_live_already_has_but_github_lacks_is_pushed_not_deployed():
    plan = tr.make_plan([facts("trainhiro", github=["a"])])
    assert plan.push == ["trainhiro"] and plan.deploys == []


def test_nothing_new_anywhere_is_an_empty_plan():
    plan = tr.make_plan([facts(r) for r in hw.REPOS])
    assert plan.empty and not plan.stops


@pytest.mark.parametrize("kw, words", [
    ({"github_ahead": True}, "GitHub has commits"),
    ({"live_ahead": True}, "the server has commits"),
    ({"server_ahead": True}, "the server has commits"),
    ({"live_dirty": 2}, "uncommitted"),
    ({"error": "GitHub couldn't be read: x"}, "couldn't be read"),
])
def test_anything_but_a_fast_forward_stops_the_deploy(kw, words):
    plan = tr.make_plan([facts("aicam", live=["a"], **kw), facts("homehiro", live=["b"])])
    assert list(plan.stops) == ["aicam"]
    assert words in plan.stops["aicam"][0]


def test_a_deploy_covers_the_repos_named_in_the_standards_order_or_every_repo():
    assert tr.choose([]) == hw.REPOS
    assert tr.choose(["nethiro", "hiroleague"]) == ["hiroleague", "nethiro"]
    with pytest.raises(hw.Stop):
        tr.choose(["nope"])


def test_a_deploy_counts_only_when_its_hook_says_so():
    assert tr.deployed("homehiro", "remote: homehiro: copying the database\nremote: homehiro: deployed\n")
    assert not tr.deployed("homehiro", "remote: homehiro: not deployed: the build failed\n")
    assert not tr.deployed("homehiro", "remote: nethiro: deployed\n")
    assert tr.deployed("hiroleague", "remote: hiroleague: deployed 20261116T101500Z-9a01574: http://... answers.\n")
    assert not tr.deployed("hiroleague", "remote: hiroleague: deploying 9a01574 as release 2026...\n")


def test_error_lines_are_counted_and_camera_addresses_hidden():
    log = ("INFO started\nERROR frigate: rtsp://user:pw@192.168.1.21:554/stream1 timed out\n"
           "Traceback (most recent call last):\nWARNING slow\nCRITICAL gone\n")
    count, shown = tr.error_lines(log, limit=2)
    assert count == 3
    assert shown[0] == "ERROR frigate: rtsp://<redacted> timed out"
    assert "pw@" not in "".join(shown)


def test_aicam_says_what_may_need_a_restart_by_top_folder():
    hints = tr.restart_hints(["talker/app.py", "talker/Dockerfile", "docs/x.md", "host/etc/x.conf", "README.md"])
    assert hints == ["host: sudo ~/aicam/host/install.sh, then ~/aicam/host/check.sh",
                     "talker: docker compose up -d talker"]


def test_a_new_apps_empty_github_repo_lacks_every_commit(tmp_path, monkeypatch):
    repo, origin = tmp_path / "env0" / "evalhiro", tmp_path / "origin.git"
    repo.mkdir(parents=True)
    hw.git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    hw.git(repo, "init", "-q", "-b", "main")
    for m in ("skeleton", "pages"):
        hw.git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", m)
    hw.git(repo, "remote", "add", "origin", str(origin))
    monkeypatch.setattr(hw, "repo_dir", lambda env, r: tmp_path / f"env{env}" / r)
    f = tr.read_facts("evalhiro", {"evalhiro": "none"})
    assert (f.error, f.github, f.live) == ("", None, None)
    assert [c.split(" ", 1)[1] for c in f.github_lacks] == ["pages", "skeleton"]
    hw.git(repo, "remote", "set-url", "origin", str(tmp_path / "nowhere.git"))  # unreachable: still an error
    assert tr.read_facts("evalhiro", {"evalhiro": "none"}).error.startswith("GitHub couldn't be read")


def app_repo(tmp_path, monkeypatch, commits=("first", "second"), name="homehiro"):
    """env0's repo (homehiro unless named) with these commits, GitHub (origin) at its main; returns each commit, oldest
    first."""
    repo, origin = tmp_path / "env0" / name, tmp_path / "origin.git"
    repo.mkdir(parents=True)
    hw.git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    hw.git(repo, "init", "-q", "-b", "main")
    shas = []
    for m in commits:
        hw.git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", m)
        shas.append(hw.git(repo, "rev-parse", "HEAD"))
    hw.git(repo, "remote", "add", "origin", str(origin))
    hw.git(repo, "push", "-q", "origin", "main")
    monkeypatch.setattr(hw, "repo_dir", lambda env, r: tmp_path / f"env{env}" / r)
    return shas


def test_what_runs_is_read_from_the_core_release_and_the_app_label():
    assert tr.runs_commit(tr.CORE, "/opt/hiroleague/releases/20261120T001038Z-ffe948187f") == "ffe948187f"
    assert tr.runs_commit(tr.CORE, "none") is None
    assert tr.runs_commit(tr.APP, "0f519ae3c0ffee") == "0f519ae3c0ffee"
    assert tr.runs_commit(tr.APP, "<no value>") is None  # an image from before the label
    assert tr.runs_commit(tr.APP, "unknown") is None     # built without deploy.sh's commit
    assert tr.runs_commit(tr.APP, "none") is None        # no container


def test_a_failed_build_leaves_the_app_not_live_and_the_next_deploy_runs_its_hook_again(tmp_path, monkeypatch):
    old, new = app_repo(tmp_path, monkeypatch)
    # The push moved Simone's repo to the new commit, but the build failed: the container runs the old image
    f = tr.read_facts("homehiro", {"homehiro": new, "homehiro-runs": old[:10]})
    assert (f.server, f.live, f.live_unknown) == (new, old, "")
    assert [c.split(" ", 1)[1] for c in f.live_lacks] == ["second"]
    plan = tr.make_plan([f])
    assert plan.then == ["homehiro"] and plan.again == ["homehiro"] and not plan.stops


def test_a_new_commit_after_a_failed_build_is_pushed_and_carries_the_failed_one(tmp_path, monkeypatch):
    old, failed, new = app_repo(tmp_path, monkeypatch, ("first", "second", "third"))
    f = tr.read_facts("homehiro", {"homehiro": failed, "homehiro-runs": old})
    assert [c.split(" ", 1)[1] for c in f.live_lacks] == ["third", "second"]
    plan = tr.make_plan([f])
    assert plan.then == ["homehiro"] and plan.again == []  # the push runs the hook itself


def test_an_app_that_runs_its_latest_is_up_to_date(tmp_path, monkeypatch):
    _, new = app_repo(tmp_path, monkeypatch)
    f = tr.read_facts("homehiro", {"homehiro": new, "homehiro-runs": new})
    assert not f.live_lacks and tr.make_plan([f]).empty


@pytest.mark.parametrize("runs, words", [("<no value>", "doesn't say its commit"), ("none", "nothing runs it")])
def test_an_app_whose_container_doesnt_say_what_it_runs_is_deployed_again(tmp_path, monkeypatch, runs, words):
    _, new = app_repo(tmp_path, monkeypatch)
    f = tr.read_facts("homehiro", {"homehiro": new, "homehiro-runs": runs})
    assert f.live is None and words in f.live_unknown and not f.live_lacks
    plan = tr.make_plan([f])
    assert plan.again == ["homehiro"] and not plan.stops


def deploy_events(path, *ends):
    """events.jsonl with these (task, repo, step, ok) ends, in order, after a task's line that is no deploy's and
    before a line cut short."""
    import json

    lines = [json.dumps({"task": "install-x", "repo": "aicam", "step": "verify", "phase": "end", "ok": False})]
    lines += [json.dumps({"task": task, "repo": repo, "step": step, "phase": "end", "ok": ok})
              for task, repo, step, ok in ends]
    lines.append('{"task": "deploy-cut')  # a line cut short
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_a_repo_whose_last_deploy_failed_its_check_is_known_and_a_later_good_deploy_clears_it(tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "EVENTS", tmp_path / "events.jsonl")
    deploy_events(hw.EVENTS, ("deploy-1", "aicam", "deploy", True), ("deploy-1", "aicam", "verify", False),
                  ("deploy-1", "homehiro", "deploy", True), ("deploy-1", "homehiro", "verify", True),
                  ("deploy-2", "nethiro", "deploy", False), ("deploy-3", "nethiro", "deploy", True),
                  ("deploy-3", "nethiro", "verify", True))
    assert tr.last_failed(["aicam", "homehiro", "nethiro"]) == {"aicam"}
    assert tr.last_failed(["homehiro"]) == set()
    hw.EVENTS.unlink()
    assert tr.last_failed(["aicam"]) == set()


def test_aicam_that_runs_its_latest_after_a_failed_check_is_deployed_again(tmp_path, monkeypatch):
    # The Nov 25 deploy: ~/aicam's pull went in, then its check found a file the pull left untracked
    _, new = app_repo(tmp_path, monkeypatch, name="aicam")
    simone = {"aicam": new, "aicam-live": new, "aicam-dirty": "0"}
    assert tr.make_plan([tr.read_facts("aicam", simone)]).empty
    f = tr.read_facts("aicam", simone, failed=True)
    assert f.last_failed and not f.live_lacks
    plan = tr.make_plan([f])
    assert plan.then == ["aicam"] and plan.again == [] and not plan.stops  # a push that carries nothing, then the pull
    said = []
    tr.show(said.append, [f], plan)
    assert any("its last deploy failed" in line and "deployed again" in line for line in said)
    assert not any("up to date" in line for line in said)


def test_an_app_that_runs_its_latest_after_a_failed_check_runs_its_hook_again(tmp_path, monkeypatch):
    _, new = app_repo(tmp_path, monkeypatch)
    f = tr.read_facts("homehiro", {"homehiro": new, "homehiro-runs": new}, failed=True)
    plan = tr.make_plan([f])
    assert plan.then == ["homehiro"] and plan.again == ["homehiro"]


def test_a_failed_deploy_that_left_the_old_commit_running_is_no_new_case(tmp_path, monkeypatch):
    old, new = app_repo(tmp_path, monkeypatch)
    f = tr.read_facts("homehiro", {"homehiro": new, "homehiro-runs": old}, failed=True)
    assert not f.last_failed and f.live_lacks  # what runs already says it isn't live


def test_running_a_commit_this_pc_lacks_stops_the_deploy(tmp_path, monkeypatch):
    _, new = app_repo(tmp_path, monkeypatch)
    f = tr.read_facts("homehiro", {"homehiro": new, "homehiro-runs": "abcdef1234"})
    assert f.live_ahead and list(tr.make_plan([f]).stops) == ["homehiro"]


def test_deploying_again_runs_the_hook_on_simone_and_a_failed_hook_is_a_failed_deploy(tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "LOGS", tmp_path)
    monkeypatch.setattr(hw, "EVENTS", tmp_path / "events.jsonl")
    monkeypatch.setattr(tr, "bare_name", lambda repo: repo)
    monkeypatch.setattr(tr, "verify", lambda *a: None)
    ran = []

    def stream(out, args, cwd, repo, log, on_line=None):
        ran.append(args)
        return (1, "homehiro: not deployed: the build failed") if len(ran) == 1 else (0, "homehiro: deployed")

    monkeypatch.setattr(tr, "stream", stream)
    f = tr.Facts(repo="homehiro", head="b" * 40, server="b" * 40, live="a" * 40)
    r = tr.Result("homehiro")
    tr.deploy(tr.Out(None), "deploy-test", f, r, again=True)
    assert ran[0][:2] == ["ssh", "-o"] and ran[0][-1] == tr.again_script(f)
    assert 'cd "$HOME/homehiro.git"' in ran[0][-1] and "| hooks/post-receive" in ran[0][-1]
    assert r.deployed is False and "didn't finish" in r.failed  # not "git refused the push"
    r = tr.Result("homehiro")
    tr.deploy(tr.Out(None), "deploy-test", f, r, again=True)
    assert r.deployed is True and not r.failed


def test_a_deploys_task_is_named_by_its_time():
    assert tr.task_id(datetime(2026, 11, 16, 14, 5, 9)) == "deploy-20261116-140509"


@pytest.fixture
def deploy_files(tmp_path, monkeypatch):
    """The deploy's log, events and lock in the test's own folder; a plan with one app; a deploy that takes 30 s."""
    clock = {"now": 1000.0}
    monkeypatch.setattr(tr.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(hw, "LOGS", tmp_path)
    monkeypatch.setattr(hw, "EVENTS", tmp_path / "events.jsonl")
    monkeypatch.setattr(tr, "LOCK", tmp_path / "run" / "deploy.lock")
    monkeypatch.setattr(tr, "gather", lambda repos: [])
    monkeypatch.setattr(tr, "make_plan", lambda facts: tr.Plan(push=["codehiro"], first=[], then=["codehiro"], stops={}))
    monkeypatch.setattr(tr, "show", lambda out, facts, plan: None)

    def deploy(out, task, facts, plan):
        clock["now"] += 30
        return []

    monkeypatch.setattr(tr, "run_deploy", deploy)
    monkeypatch.setattr(tr, "report", lambda out, task, results, started: True)
    return tmp_path


def run_here():
    tr.cmd_deploy(type("A", (), {"repos": ["codehiro"], "dry_run": False, "here": True, "id": None, "stop": False,
                                "force": False})())


def ends(task):
    return [e for e in tr.events_of(task) if e["step"] == "task" and e["phase"] == "end"]


def test_a_deploy_runs_without_asking_and_frees_its_lock(deploy_files, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _q: pytest.fail("the deploy asked a question"))
    monkeypatch.setattr(tr, "task_id", lambda now: "deploy-test")
    run_here()
    [end] = ends("deploy-test")
    assert (end["ok"], end["seconds"]) == (True, 30)
    assert not tr.LOCK.exists()


def test_a_lock_whose_deploy_is_gone_is_taken_over_and_that_deploy_closed(deploy_files, monkeypatch):
    monkeypatch.setattr(tr, "task_id", lambda now: "deploy-new")
    hw.event(task="deploy-old", env=0, step="task", phase="start", kind="deploy")
    hw.event(task="deploy-old", env=0, repo="codehiro", step="deploy", phase="start")
    tr.LOCK.parent.mkdir(parents=True)
    tr.LOCK.write_text("999999 deploy-old", encoding="utf-8")
    monkeypatch.setattr(tr, "alive", lambda pid: False)
    run_here()
    [old] = ends("deploy-old")
    assert old["ok"] is False and "gone" in old["error"]
    assert [e for e in tr.events_of("deploy-old") if e["step"] == "deploy" and e["phase"] == "end"]
    assert ends("deploy-new")[0]["ok"] is True


def test_a_running_deploy_refuses_the_next_and_its_log_says_why(deploy_files, monkeypatch):
    monkeypatch.setattr(tr, "task_id", lambda now: "deploy-next")
    tr.LOCK.parent.mkdir(parents=True)
    tr.LOCK.write_text("4242 deploy-busy", encoding="utf-8")
    monkeypatch.setattr(tr, "alive", lambda pid: True)
    with pytest.raises(hw.Stop, match="deploy-busy"):
        run_here()
    assert tr.REFUSED in (deploy_files / "deploy" / "deploy-next.log").read_text(encoding="utf-8")
    assert tr.LOCK.read_text(encoding="utf-8") == "4242 deploy-busy"  # not its lock to take


def test_stop_waits_out_a_push_unless_forced_and_closes_the_deploy(deploy_files, monkeypatch):
    killed = []
    monkeypatch.setattr(tr.subprocess, "run", lambda cmd, **kw: killed.append(cmd))
    monkeypatch.setattr(tr, "alive", lambda pid: True)
    hw.event(task="deploy-run", env=0, step="task", phase="start", kind="deploy")
    hw.event(task="deploy-run", env=0, repo="codehiro", step="push github", phase="start")
    tr.LOCK.parent.mkdir(parents=True)
    tr.LOCK.write_text("4242 deploy-run", encoding="utf-8")
    with pytest.raises(hw.Stop, match="push github"):
        tr.cmd_stop(force=False)
    assert not killed and not ends("deploy-run")
    tr.cmd_stop(force=True)
    assert killed and ends("deploy-run")[0]["ok"] is False and not tr.LOCK.exists()


def test_a_deploy_with_nothing_to_ship_says_so_and_ends_well(deploy_files, monkeypatch):
    monkeypatch.setattr(tr, "task_id", lambda now: "deploy-empty")
    monkeypatch.setattr(tr, "make_plan", lambda facts: tr.Plan(push=[], first=[], then=[], stops={}))
    run_here()
    assert ends("deploy-empty")[0]["ok"] is True
    assert "Nothing to ship" in (deploy_files / "deploy" / "deploy-empty.log").read_text(encoding="utf-8")
    # No step of any repo: CodeHiro's Deployments reads that as "Nothing to ship"
    assert not [e for e in tr.events_of("deploy-empty") if e.get("repo")]


def test_a_repo_runs_what_the_deploy_read_only_when_its_part_went_well():
    plan = tr.Plan(push=["hiroleague", "codehiro", "nethiro", "hiro-docs"], first=["hiroleague"],
                   then=["codehiro", "nethiro", "studyhiro"], stops={})
    results = [tr.Result("hiroleague", deployed=True, answers=True), tr.Result("codehiro", deployed=True, errors=2),
               tr.Result("nethiro"),  # its turn never came: no deployed
               tr.Result("studyhiro", deployed=False, failed="build failed"), tr.Result("hiro-docs", pushed=1)]
    names = ["hiroleague", "codehiro", "nethiro", "studyhiro", "hiro-docs", "trainhiro"]
    assert tr.runs_head([facts(n) for n in names], plan, results) == {"hiroleague", "hiro-docs", "trainhiro"}


def test_the_deploy_moves_plan_phases_live_with_what_it_read_and_what_runs_it(deploy_files, monkeypatch):
    import plan

    calls = []
    monkeypatch.setattr(plan, "went_live", lambda heads, live: calls.append((heads, live)) or ["Plan X: moved"])
    monkeypatch.setattr(tr, "task_id", lambda now: "deploy-live")
    monkeypatch.setattr(tr, "gather", lambda repos: [facts("codehiro")])
    monkeypatch.setattr(tr, "run_deploy", lambda out, task, facts, plan: [tr.Result("codehiro", deployed=True)])
    run_here()
    assert calls == [({"codehiro": "h"}, {"codehiro"})]
    assert "Plan X: moved" in (deploy_files / "deploy" / "deploy-live.log").read_text(encoding="utf-8")
    monkeypatch.setattr(tr, "task_id", lambda now: "deploy-empty")
    monkeypatch.setattr(tr, "make_plan", lambda facts: tr.Plan(push=[], first=[], then=[], stops={}))
    run_here()  # nothing to ship: what ran already counts, so a phase merged earlier catches up
    assert calls[-1] == ({"codehiro": "h"}, {"codehiro"})
