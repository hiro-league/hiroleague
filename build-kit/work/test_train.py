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


def test_github_gets_every_repo_it_lacks_commits_of_and_hiro_docs_only_goes_there():
    plan = tr.make_plan([facts("homehiro", github=["a"], live=["a"]), facts("hiro-docs", github=["d"], live=["d"]),
                         facts("nethiro", live=["n"])])
    assert plan.push == ["homehiro", "hiro-docs"]
    assert plan.deploys == ["homehiro", "nethiro"]


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


def test_a_trains_task_is_named_by_its_time():
    assert tr.task_id(datetime(2026, 11, 16, 14, 5, 9)) == "train-20261116-140509"


def test_a_trains_time_runs_from_the_go_not_from_the_question(monkeypatch, tmp_path):
    clock = {"now": 1000.0}
    events = []
    monkeypatch.setattr(tr.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(hw, "event", lambda **e: events.append(e))
    monkeypatch.setattr(hw, "LOGS", tmp_path)
    monkeypatch.setattr(hw, "RUN", tmp_path / "run")
    monkeypatch.setattr(tr, "gather", lambda repos: [])
    monkeypatch.setattr(tr, "make_plan", lambda facts: tr.Plan(push=["codehiro"], first=[], then=["codehiro"], stops={}))
    monkeypatch.setattr(tr, "show", lambda out, facts, plan: None)
    monkeypatch.setattr(tr.sys.stdin, "isatty", lambda: True)

    def answer(_question):
        clock["now"] += 200  # Michel reads the plan for 200 s
        return "y"

    def deploy(out, task, facts, plan):
        clock["now"] += 30  # the train itself
        return []

    monkeypatch.setattr("builtins.input", answer)
    monkeypatch.setattr(tr, "run_train", deploy)
    monkeypatch.setattr(tr, "report", lambda out, task, results, started: True)
    args = type("A", (), {"repos": ["codehiro"], "dry_run": False, "here": True, "id": "train-test", "yes": False})()
    tr.cmd_train(args)
    end = [e for e in events if e["step"] == "task" and e["phase"] == "end"][0]
    assert (end["ok"], end["seconds"]) == (True, 30)
