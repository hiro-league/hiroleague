"""The deploy train's choices: what lacks what, what stops it, the order (the core first, the rest side by side)."""

from datetime import datetime

import pytest

import hiro_work as hw
import train as tr


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
def test_anything_but_a_fast_forward_stops_the_train(kw, words):
    plan = tr.make_plan([facts("aicam", live=["a"], **kw), facts("homehiro", live=["b"])])
    assert list(plan.stops) == ["aicam"]
    assert words in plan.stops["aicam"][0]


def test_a_train_covers_the_repos_named_in_the_standards_order_or_every_repo():
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


def test_a_trains_task_is_named_by_its_time():
    assert tr.task_id(datetime(2026, 11, 16, 14, 5, 9)) == "train-20261116-140509"


@pytest.fixture
def train_files(tmp_path, monkeypatch):
    """The train's log, events and lock in the test's own folder; a plan with one app; a deploy that takes 30 s."""
    clock = {"now": 1000.0}
    monkeypatch.setattr(tr.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(hw, "LOGS", tmp_path)
    monkeypatch.setattr(hw, "EVENTS", tmp_path / "events.jsonl")
    monkeypatch.setattr(tr, "LOCK", tmp_path / "run" / "train.lock")
    monkeypatch.setattr(tr, "gather", lambda repos: [])
    monkeypatch.setattr(tr, "make_plan", lambda facts: tr.Plan(push=["codehiro"], first=[], then=["codehiro"], stops={}))
    monkeypatch.setattr(tr, "show", lambda out, facts, plan: None)

    def deploy(out, task, facts, plan):
        clock["now"] += 30
        return []

    monkeypatch.setattr(tr, "run_train", deploy)
    monkeypatch.setattr(tr, "report", lambda out, task, results, started: True)
    return tmp_path


def run_here():
    tr.cmd_train(type("A", (), {"repos": ["codehiro"], "dry_run": False, "here": True, "id": None, "stop": False,
                                "force": False})())


def ends(task):
    return [e for e in tr.events_of(task) if e["step"] == "task" and e["phase"] == "end"]


def test_a_train_runs_without_asking_and_frees_its_lock(train_files, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _q: pytest.fail("the train asked a question"))
    monkeypatch.setattr(tr, "task_id", lambda now: "train-test")
    run_here()
    [end] = ends("train-test")
    assert (end["ok"], end["seconds"]) == (True, 30)
    assert not tr.LOCK.exists()


def test_a_lock_whose_train_is_gone_is_taken_over_and_that_train_closed(train_files, monkeypatch):
    monkeypatch.setattr(tr, "task_id", lambda now: "train-new")
    hw.event(task="train-old", env=0, step="task", phase="start", kind="deploy")
    hw.event(task="train-old", env=0, repo="codehiro", step="deploy", phase="start")
    tr.LOCK.parent.mkdir(parents=True)
    tr.LOCK.write_text("999999 train-old", encoding="utf-8")
    monkeypatch.setattr(tr, "alive", lambda pid: False)
    run_here()
    [old] = ends("train-old")
    assert old["ok"] is False and "gone" in old["error"]
    assert [e for e in tr.events_of("train-old") if e["step"] == "deploy" and e["phase"] == "end"]
    assert ends("train-new")[0]["ok"] is True


def test_a_running_train_refuses_the_next_and_its_log_says_why(train_files, monkeypatch):
    monkeypatch.setattr(tr, "task_id", lambda now: "train-next")
    tr.LOCK.parent.mkdir(parents=True)
    tr.LOCK.write_text("4242 train-busy", encoding="utf-8")
    monkeypatch.setattr(tr, "alive", lambda pid: True)
    with pytest.raises(hw.Stop, match="train-busy"):
        run_here()
    assert tr.REFUSED in (train_files / "train" / "train-next.log").read_text(encoding="utf-8")
    assert tr.LOCK.read_text(encoding="utf-8") == "4242 train-busy"  # not its lock to take


def test_stop_waits_out_a_push_unless_forced_and_closes_the_train(train_files, monkeypatch):
    killed = []
    monkeypatch.setattr(tr.subprocess, "run", lambda cmd, **kw: killed.append(cmd))
    monkeypatch.setattr(tr, "alive", lambda pid: True)
    hw.event(task="train-run", env=0, step="task", phase="start", kind="deploy")
    hw.event(task="train-run", env=0, repo="codehiro", step="push github", phase="start")
    tr.LOCK.parent.mkdir(parents=True)
    tr.LOCK.write_text("4242 train-run", encoding="utf-8")
    with pytest.raises(hw.Stop, match="push github"):
        tr.cmd_stop(force=False)
    assert not killed and not ends("train-run")
    tr.cmd_stop(force=True)
    assert killed and ends("train-run")[0]["ok"] is False and not tr.LOCK.exists()
