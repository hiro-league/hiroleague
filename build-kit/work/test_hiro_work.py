"""hiro-work's choices: the ports of an environment, what a task reserves, where a new task goes."""

import json
import threading
import time

import pytest

import hiro_work as hw


def task(id, env, repos, state="working"):
    return hw.Task(id=id, title=id, env=env, repos=repos, state=state)


def test_each_environment_owns_17_consecutive_ports():
    assert hw.ports(0)["core-admin"] == 7000
    assert hw.ports(2)["core-socket"] == 7201
    assert hw.ports(5)["codehiro-ui"] == 7512
    assert hw.ports(1)["core-plugin"] == 7114
    assert hw.ports(4)["evalhiro-ui"] == 7416
    assert sorted(hw.ports(3).values()) == list(range(7300, 7317))


def test_reserves_keep_the_core_first_and_a_kit_change_reserves_the_apps():
    assert hw.expand(["homehiro", "hiroleague"], kit=False) == ["hiroleague", "homehiro"]
    assert hw.expand(["hiroleague"], kit=True) == ["hiroleague", "homehiro", "nethiro", "trainhiro", "studyhiro",
                                                    "codehiro", "evalhiro"]
    with pytest.raises(hw.Stop):
        hw.expand(["nope"], kit=False)


def test_a_task_never_works_in_env0_the_trunk():
    assert hw.pick_env([], None) == 1
    with pytest.raises(hw.Stop, match="main"):
        hw.pick_env([], 0)


def test_a_task_goes_to_the_first_free_environment():
    tasks = [task("a", 1, ["hiroleague", "homehiro"]), task("b", 3, ["nethiro"])]
    assert hw.pick_env(tasks, None) == 2


def test_paused_tasks_hold_no_environment():
    tasks = [task("a", None, ["homehiro"], state="paused")]
    assert hw.pick_env(tasks, None) == 1


def test_asking_for_a_busy_environment_is_refused():
    with pytest.raises(hw.Stop):
        hw.pick_env([task("a", 3, ["nethiro"])], 3)
    assert hw.pick_env([task("a", 3, ["nethiro"])], 4) == 4


def test_a_step_of_open_work_joins_it_unless_michel_gives_it_its_own_branch(tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "TASKS", tmp_path)
    plan = hw.Task(id="plan", title="Memory plan", env=1, repos=["hiroleague"])
    step1 = hw.Task(id="step1", title="Step 1", env=2, repos=["evalhiro"], part_of="Memory plan")
    paused = hw.Task(id="old", title="Old", env=None, repos=["homehiro"], state="paused", part_of="Other plan")
    for t in (plan, step1, paused):
        hw.save(t)
    tasks = hw.load_tasks()
    assert [t.id for t in hw.same_work("plan", tasks)] == ["plan", "step1"]  # by id: the task and its pieces
    assert [t.id for t in hw.same_work("Memory plan", tasks)] == ["plan", "step1"]  # by name
    assert [t.id for t in hw.same_work("Other plan", tasks)] == ["old"]  # a paused piece counts
    assert hw.same_work("New work", tasks) == [] and hw.same_work("", tasks) == []
    args = dict(task="step2", repos="nethiro", kit=False, title=None, env=None, part_of="plan", about=None,
                preset="Safe", set=None, data="env0", own_branch=False)
    with pytest.raises(hw.Stop, match="guard.py join"):
        hw.cmd_start(hw.argparse.Namespace(**args))
    assert not hw.task_path("step2").exists()  # refused before any reserve


def test_a_task_record_from_a_newer_hiro_work_is_read_and_its_new_fields_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "TASKS", tmp_path)
    (tmp_path / "t.json").write_text('{"id": "t", "title": "t", "env": 3, "repos": ["hiroleague"], "real": ["ai"]}',
                                     encoding="utf-8")
    [t] = hw.load_tasks()
    assert (t.id, t.env) == ("t", 3)
    t.title = "renamed"
    hw.save(t)
    saved = hw.json.loads((tmp_path / "t.json").read_text(encoding="utf-8"))
    assert saved["real"] == ["ai"] and saved["title"] == "renamed"


def test_when_every_environment_is_busy_a_new_task_is_refused():
    tasks = [task(f"t{e}", e, ["nethiro"]) for e in range(1, 6)]
    with pytest.raises(hw.Stop):
        hw.pick_env(tasks, None)


def test_launch_json_lists_each_repos_servers_on_the_environments_own_ports(tmp_path, monkeypatch):
    for name in ("ROOT", "RUN", "LOGS", "TASKS"):
        monkeypatch.setattr(hw, name, tmp_path / name.lower())
    configs = hw.launch_configs(3)
    assert sorted(configs) == sorted(["hiroleague", *hw.SERVED])  # aicam has no servers in the table
    assert [c["name"] for c in configs["hiroleague"]] == ["core", "core-ui"]
    ports = [c["port"] for repo in configs.values() for c in repo]
    p = hw.ports(3)  # the core's server is its admin API; its other listeners come with it
    apps = [p[f"{a}-{side}"] for a in hw.SERVED for side in ("api", "ui")]
    assert sorted(ports) == sorted([p["core-admin"], p["core-ui"], *apps])
    homehiro_api = configs["homehiro"][0]  # the pane opens what `up` started; it never starts a server itself
    assert homehiro_api == {"name": "homehiro-api", "url": f"http://127.0.0.1:{p['homehiro-api']}",
                            "port": p["homehiro-api"]}


def test_up_takes_server_app_and_port_names(tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "TASKS", tmp_path)
    names = lambda *n: [s.name for s in hw.pick_servers(2, list(n))]  # noqa: E731
    assert names("codehiro") == ["codehiro-api", "codehiro-ui"]
    assert names("core-admin", "core-socket", "homehiro-ui") == ["core", "homehiro-ui"]
    assert names() == ["core", "core-ui", *[f"{a}-{s}" for a in hw.SERVED for s in ("api", "ui")]]
    with pytest.raises(hw.Stop, match="start the core"):
        names("nope")


def _events(tmp_path, monkeypatch):
    """hiro-work's events go to a log of the test's own (never the real one, which the sender sends)."""
    monkeypatch.setattr(hw, "LOGS", tmp_path)
    monkeypatch.setattr(hw, "EVENTS", tmp_path / "events.jsonl")
    return lambda: [json.loads(x) for x in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()]


def test_a_step_inside_another_names_it_as_its_parent(tmp_path, monkeypatch):
    read = _events(tmp_path, monkeypatch)
    with hw.step("t", 1, "merge"):
        with hw.step("t", 1, "check", "codehiro"):
            pass
    with hw.step("t", 1, "after"):
        pass
    by = {(e["step"], e["phase"]): e for e in read()}
    assert "parent" not in by[("merge", "start")]
    assert by[("check", "start")]["parent"] == "merge" and by[("check", "end")]["parent"] == "merge"
    assert "parent" not in by[("after", "start")]


def _checks_side_by_side(tmp_path, monkeypatch, free: float):
    """check_repos over the core and three apps, each check a short sleep; returns (the order the checks started in,
    the most that ran at once, the events)."""
    read = _events(tmp_path, monkeypatch)
    lock, now, most, started = threading.Lock(), [0], [0], []

    def check_repo(task, env, repo, failed):
        with hw.step(task.id, env, "check", repo):
            with lock:
                started.append(repo)
                now[0] += 1
                most[0] = max(most[0], now[0])
            time.sleep(0.2)
            with lock:
                now[0] -= 1

    monkeypatch.setattr(hw, "check_repo", check_repo)
    monkeypatch.setattr(hw, "runs_alone", lambda env, repo: repo == "hiroleague")
    monkeypatch.setattr(hw, "free_gb", lambda: free)
    monkeypatch.setattr(hw, "MERGE_POLL", 0.02)
    t = hw.Task(id="t", title="t", env=1, repos=["hiroleague"])
    with hw.step("t", 1, "merge"):
        assert hw.check_repos(t, 1, ["homehiro", "hiroleague", "nethiro", "codehiro"]) == []
    return started, most[0], read()


def test_a_merges_checks_run_the_core_alone_then_two_apps_at_a_time(tmp_path, monkeypatch):
    started, most, events = _checks_side_by_side(tmp_path, monkeypatch, free=32.0)
    assert started[0] == "hiroleague" and sorted(started[1:]) == ["codehiro", "homehiro", "nethiro"]
    assert most == 2
    checks = [e for e in events if e["step"] == "check"]
    assert len(checks) == 8 and all(e["parent"] == "merge" for e in checks)  # each thread's step is the merge's


def test_a_merges_second_check_waits_for_free_memory(tmp_path, monkeypatch):
    _, most, _ = _checks_side_by_side(tmp_path, monkeypatch, free=hw.MERGE_MIN_FREE_GB - 1)
    assert most == 1


def test_a_step_can_fail_without_stopping_and_carries_its_logs_last_lines(tmp_path, monkeypatch):
    read = _events(tmp_path, monkeypatch)
    log = tmp_path / "check.log"
    log.write_text("\n".join(f"line {i}" for i in range(150)), encoding="utf-8")
    with hw.step("t", 1, "check", "codehiro", log=log) as outcome:
        outcome.fail("check.sh failed")
    end = read()[-1]
    assert (end["ok"], end["error"], end["log"] if "log" in end else None) == (False, "check.sh failed", None)
    assert read()[0]["log"] == str(log)
    assert end["tail"].splitlines() == [f"line {i}" for i in range(50, 150)]


def test_servers_up_names_its_servers_on_both_events(tmp_path, monkeypatch):
    read = _events(tmp_path, monkeypatch)
    with hw.step(None, 2, "servers up", servers=["core", "core-ui"]):
        pass
    assert [e["servers"] for e in read()] == [["core", "core-ui"], ["core", "core-ui"]]


def test_review_marks_a_working_task_and_refuses_a_paused_one(tmp_path, monkeypatch):
    read = _events(tmp_path, monkeypatch)
    monkeypatch.setattr(hw, "TASKS", tmp_path / "tasks")
    hw.TASKS.mkdir()
    hw.save(task("t", 1, ["codehiro"]))
    hw.cmd_review(type("A", (), {"task": "t"})())
    assert read()[-1] == {**read()[-1], "task": "t", "env": 1, "step": "review", "phase": "start"}
    hw.save(task("p", None, ["codehiro"], state="paused"))
    with pytest.raises(hw.Stop):
        hw.cmd_review(type("A", (), {"task": "p"})())


def test_sweep_leaves_out_branches_in_use():
    listing = "* dev\n+ task/open-one\n  task/old\n  main\n  (HEAD detached at 1234)\n"
    assert hw.merged_left(listing, "dev") == ["task/old"]


def test_a_merge_records_the_commits_it_added(tmp_path, monkeypatch):
    read = _events(tmp_path, monkeypatch)
    repo = tmp_path / "env0" / "codehiro"
    repo.mkdir(parents=True)
    run = lambda *a: hw.git(repo, *a)  # noqa: E731
    run("init", "-q")
    run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "one")
    before = run("rev-parse", "HEAD")
    run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "two")
    run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "three")
    after = run("rev-parse", "HEAD")
    monkeypatch.setattr(hw, "repo_dir", lambda env, r: tmp_path / f"env{env}" / r)
    hw.record_commits("t", 1, "codehiro", before, after, "merge")
    hw.record_commits("t", 1, "codehiro", after, after, "merge")  # nothing new: no event
    [e] = read()
    assert (e["step"], e["how"], e["from"], e["to"], len(e["commits"])) == ("commits", "merge", before, after, 2)
    assert e["commits"][0] == after


def test_a_merge_merges_env0_into_a_new_app_that_has_no_github_repo_yet(tmp_path, monkeypatch):
    _events(tmp_path, monkeypatch)
    for who in ("AUTHOR", "COMMITTER"):  # the merge commit needs a name: the core's deploy has no git identity
        monkeypatch.setenv(f"GIT_{who}_NAME", "t")
        monkeypatch.setenv(f"GIT_{who}_EMAIL", "t@t")
    repo = tmp_path / "env1" / "evalhiro"
    repo.mkdir(parents=True)
    run = lambda *a: hw.git(repo, *a)  # noqa: E731
    commit = lambda m: run("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", m)  # noqa: E731
    run("init", "-q", "-b", "main")
    commit("skeleton")
    run("checkout", "-q", "-b", "task/t")
    commit("pages")
    run("checkout", "-q", "main")
    commit("merged by another task")
    run("checkout", "-q", "task/t")
    monkeypatch.setattr(hw, "repo_dir", lambda env, r: tmp_path / f"env{env}" / r)
    hw.merge_latest(hw.Task(id="t", title="t", env=1, repos=["evalhiro"]), 1)  # no origin: only main is merged
    assert run("merge-base", "--is-ancestor", "main", "HEAD") == ""  # raised if main weren't in the branch


def test_sync_brings_the_trunk_into_a_tasks_branch_without_merging(tmp_path, monkeypatch):
    read = _events(tmp_path, monkeypatch)
    monkeypatch.setattr(hw, "TASKS", tmp_path / "tasks")
    hw.TASKS.mkdir()
    monkeypatch.setattr(hw, "REPOS", ["evalhiro"])
    monkeypatch.setattr(hw, "repo_dir", lambda env, r: tmp_path / f"env{env}" / r)
    monkeypatch.setattr(hw, "install", lambda *a, **k: [])
    for who in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{who}_NAME", "t")
        monkeypatch.setenv(f"GIT_{who}_EMAIL", "t@t")
    repo = _repo(tmp_path / "env1" / "evalhiro", "skeleton")
    run = lambda *a: hw.git(repo, *a)  # noqa: E731
    run("checkout", "-q", "-b", "task/t")
    run("commit", "-q", "--allow-empty", "-m", "phase 1")
    run("checkout", "-q", "main")
    run("commit", "-q", "--allow-empty", "-m", "merged by another task")
    run("checkout", "-q", "task/t")
    hw.save(task("t", 1, ["evalhiro"]))
    hw.cmd_sync(hw.argparse.Namespace(task="t"))
    assert run("merge-base", "--is-ancestor", "main", "HEAD") == ""  # raised if main weren't in the branch
    assert run("branch", "--show-current") == "task/t" and hw.get("t").state == "working"  # not merged
    assert [e["step"] for e in read() if e["phase"] == "end"][-1] == "sync"


def test_a_merge_stops_the_environments_servers_before_it_installs_anything(tmp_path, monkeypatch):
    _events(tmp_path, monkeypatch)
    order = []

    class Installing(Exception):
        pass

    def install(env, repo, task=None, force=False):
        order.append(("install", env, repo))
        raise Installing  # the first install is all this test needs to see

    repo = tmp_path / "env1" / "codehiro"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "check.sh").write_text("")
    monkeypatch.setattr(hw, "repo_dir", lambda env, r: tmp_path / f"env{env}" / r)
    monkeypatch.setattr(hw, "servers_down", lambda env, names=None: order.append(("down", env)))
    monkeypatch.setattr(hw, "merge_latest", lambda task, env: order.append(("merge", env)))
    monkeypatch.setattr(hw, "kit_changed", lambda env, task: False)
    monkeypatch.setattr(hw, "install", install)
    with pytest.raises(Installing):
        hw.merge_steps(hw.Task(id="t", title="t", env=1, repos=["codehiro"]), 1)
    assert order == [("down", 1), ("merge", 1), ("install", 1, "codehiro")]  # only env1's servers; never env0's


def _node_repo(tmp_path, monkeypatch, up: set[int]):
    """env0's homehiro with one frontend, npm replaced by a list of its calls, `up` the ports that answer."""
    _events(tmp_path, monkeypatch)
    sub = hw.NODE["homehiro"][0]
    (tmp_path / "env0" / "homehiro" / sub / "node_modules").mkdir(parents=True, exist_ok=True)
    (tmp_path / "env0" / "homehiro" / sub / "package-lock.json").write_text("{}")
    calls = []
    monkeypatch.setattr(hw, "repo_dir", lambda env, r: tmp_path / f"env{env}" / r)
    monkeypatch.setattr(hw, "PYTHON", {})
    monkeypatch.setattr(hw, "run", lambda cmd, **kw: calls.append(cmd))
    monkeypatch.setattr(hw, "listening", lambda port: port in up)
    return calls


def test_an_install_waits_when_the_servers_run_on_those_packages(tmp_path, monkeypatch):
    ui_port = hw.ports(0)["homehiro-ui"]
    calls = _node_repo(tmp_path, monkeypatch, {ui_port})
    assert hw.install(0, "homehiro", force=True, spare_servers=True) == ["homehiro-ui"]
    assert calls == []  # npm ci never ran under the running Vite


def test_an_install_runs_when_the_servers_are_down_or_not_spared(tmp_path, monkeypatch):
    calls = _node_repo(tmp_path, monkeypatch, set())
    assert hw.install(0, "homehiro", force=True, spare_servers=True) == []
    assert len(calls) == 1 and calls[0][:2] == ["npm.cmd", "ci"]
    calls = _node_repo(tmp_path, monkeypatch, {hw.ports(0)["homehiro-ui"]})
    hw.install(0, "homehiro", force=True)  # envN installs run after merge stopped the servers
    assert len(calls) == 1


def test_only_the_cores_admin_and_an_apps_frontend_have_a_dev_server(tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "listening", lambda port: True)
    assert hw.ui_server_up(0, "hiroleague", "admin_frontend") == "core-ui"
    assert hw.ui_server_up(0, "hiroleague", "ui-kit") is None


def test_the_install_command_names_the_server_to_stop(tmp_path, monkeypatch, capsys):
    _node_repo(tmp_path, monkeypatch, {hw.ports(0)["homehiro-ui"]})
    monkeypatch.setattr(hw, "needs_install", lambda stamp, lock, force: True)
    with pytest.raises(hw.Stop, match="hiro-work down 0 homehiro-ui"):
        hw.cmd_install(hw.argparse.Namespace(env=0, repos=["homehiro"]))
    assert "hiro-work install 0 homehiro" in hw.waiting_installs_note({"homehiro": ["homehiro-ui"]})


def test_part_of_is_a_name_or_a_tasks_title(tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "TASKS", tmp_path)
    hw.save(hw.Task(id="plan", title="Work-flow plan", env=0, repos=["hiro-docs"]))
    (tmp_path / "done").mkdir()
    (tmp_path / "done" / "old.json").write_text(json.dumps({"id": "old", "title": "Old work"}), encoding="utf-8")
    assert hw.part_of_name("plan") == "Work-flow plan"
    assert hw.part_of_name("old") == "Old work"
    assert hw.part_of_name(" Work-flow plan ") == "Work-flow plan"
    assert hw.part_of_name(None) == ""


def test_the_work_card_says_what_a_task_is_part_of(capsys):
    hw.card(hw.Task(id="t", title="T", env=0, repos=["codehiro"], part_of="Work-flow plan"))
    assert "Task t (part of Work-flow plan): env0" in capsys.readouterr().out


def test_describe_changes_what_a_task_does_or_what_it_is_part_of_and_says_so(tmp_path, monkeypatch):
    read = _events(tmp_path, monkeypatch)
    monkeypatch.setattr(hw, "TASKS", tmp_path / "tasks")
    hw.TASKS.mkdir()
    hw.save(hw.Task(id="t", title="T", env=1, repos=["codehiro"], part_of="Work-flow plan"))
    args = lambda about=None, part_of=None: type("A", (), {"task": "t", "about": about, "part_of": part_of})()  # noqa: E731
    hw.cmd_describe(args(about=" Shows each deploy's stages ", part_of=""))
    assert (hw.get("t").about, hw.get("t").part_of) == ("Shows each deploy's stages", "")
    e = read()[-1]
    assert (e["step"], e["phase"], e["about"], e["part_of"]) == ("describe", "end", "Shows each deploy's stages", "")
    hw.cmd_describe(args(about="Better words"))
    assert "part_of" not in read()[-1]  # only what changed
    with pytest.raises(hw.Stop):
        hw.cmd_describe(args())


def test_the_work_card_says_what_a_task_does(capsys):
    hw.card(hw.Task(id="t", title="T", env=0, repos=["codehiro"], about="Shows each deploy's stages"))
    assert "  Shows each deploy's stages" in capsys.readouterr().out


def test_up_points_every_app_at_its_environment_env0_too(tmp_path, monkeypatch):
    import sqlite3

    monkeypatch.setattr(hw, "ROOT", tmp_path)
    home, reports = hw.appfile.BY_REPO["homehiro"], hw.appfile.BY_REPO["codehiro"]
    for a in (home, reports):
        folder = hw.app_data(0, a)
        folder.mkdir(parents=True)
        with sqlite3.connect(folder / a.settings_db) as con:
            con.execute("create table setting (key text primary key, value text not null)")
    hw.configure_apps(0, [home, reports])
    read = lambda a, key: sqlite3.connect(hw.app_data(0, a) / a.settings_db).execute(  # noqa: E731
        "select value from setting where key = ?", (key,)).fetchone()[0]
    assert read(home, "homehiro_url") == "http://127.0.0.1:7004"  # the dev site, not homehiro.local
    assert read(reports, "reports_url") == "http://127.0.0.1:7012"
    assert read(reports, "hiroleague_url") == "ws://127.0.0.1:7001"
    assert hw.app_data(0, reports) == tmp_path / "env0" / "codehiro" / "data"  # env0 keeps it in the repo


def test_an_app_is_paired_only_when_this_core_knows_its_key(tmp_path, monkeypatch):
    import sqlite3

    monkeypatch.setattr(hw, "ROOT", tmp_path)
    net = hw.appfile.BY_REPO["nethiro"]
    assert not hw.paired(1, net)  # no key at all
    keys = hw.app_data(1, net) / "hiroleague"
    keys.mkdir(parents=True)
    (keys / "extension_identity.json").write_text('{"extension_id": "abc"}', encoding="utf-8")
    db = hw.core_workspace(1) / "db" / "workspace.db"
    db.parent.mkdir(parents=True)
    with sqlite3.connect(db) as con:
        con.execute("create table extensions (extension_id text)")
    assert not hw.paired(1, net)  # a key this core doesn't know
    with sqlite3.connect(db) as con:
        con.execute("insert into extensions values ('abc')")
    assert hw.paired(1, net)


def test_overlaps_name_tasks_on_the_same_repos_or_the_kit_beside_an_app():
    me = task("me", 1, ["codehiro"])
    others = [me, task("same", 0, ["codehiro", "hiro-docs"]), task("kit", 2, ["hiroleague"]),
              task("apart", 3, ["aicam"]), task("paused", None, ["codehiro"], state="paused")]
    lines = hw.overlaps(me, others)
    assert len(lines) == 2
    assert lines[0].startswith("codehiro: also changed by same (env0")
    assert lines[1].startswith("the core's kits and an app that reads them: also changed by kit (env2")


def _repo(path, *commits):
    path.mkdir(parents=True)
    hw.git(path, "init", "-q", "-b", "main")
    for c in commits:
        hw.git(path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", c)
    return path


def test_an_environments_other_repos_follow_env0_when_clean_and_behind(tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "ROOT", tmp_path)
    monkeypatch.setattr(hw, "REPOS", ["hiroleague", "codehiro", "nethiro"])
    monkeypatch.setattr(hw, "MAIN", {})
    for repo in ("hiroleague", "nethiro"):
        _repo(tmp_path / "env0" / repo, "one")
        hw.git(tmp_path / "env0" / repo, "worktree", "add", "-q", "--detach", str(tmp_path / "env1" / repo), "main")
        hw.git(tmp_path / "env0" / repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty",
               "-m", "two")
    (tmp_path / "env1" / "nethiro" / "edit.txt").write_text("mine", encoding="utf-8")  # someone's unfinished edit
    notes = hw.bring_up_others(1, task("t", 1, ["codehiro"]))
    core0, core1 = (hw.git(tmp_path / f"env{e}" / "hiroleague", "rev-parse", "HEAD") for e in (0, 1))
    assert core1 == core0 and any("hiroleague: brought up" in n for n in notes)
    assert any("nethiro: has uncommitted files" in n for n in notes)
    assert hw.bring_up_others(0, task("t", 0, ["codehiro"])) == []  # env0 is the source


def test_a_command_opens_no_console_window(monkeypatch):
    """The relay runs as pythonw: each git it started opened a console window, flashing every minute."""
    seen = {}

    def fake(args, **kw):
        seen.update(kw)
        return hw.subprocess.CompletedProcess(args, 0, "ok", "")

    monkeypatch.setattr(hw.subprocess, "run", fake)
    assert hw.run(["git", "status"]) == "ok"
    assert seen["creationflags"] == getattr(hw.subprocess, "CREATE_NO_WINDOW", 0)


def test_changed_repos_are_a_reserves_new_work_or_any_uncommitted_files(tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "ROOT", tmp_path)
    monkeypatch.setattr(hw, "REPOS", ["hiroleague", "codehiro", "nethiro", "homehiro"])
    for repo in ("hiroleague", "codehiro", "nethiro"):
        _repo(tmp_path / "env1" / repo, "one")
    t = task("t", 1, ["hiroleague", "codehiro"])
    t.base = {r: hw.git(tmp_path / "env1" / r, "rev-parse", "HEAD") for r in t.repos}
    assert hw.changed_repos(1, [t]) == []  # reserved, nothing new; homehiro isn't there
    (tmp_path / "env1" / "codehiro" / "edit.txt").write_text("mine", encoding="utf-8")
    (tmp_path / "env1" / "nethiro" / "stray.txt").write_text("someone's", encoding="utf-8")
    hw.git(tmp_path / "env1" / "hiroleague", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
           "--allow-empty", "-m", "two")
    assert hw.changed_repos(1, [t]) == ["hiroleague", "codehiro", "nethiro"]  # a commit, an edit, a stray file
    assert hw.changed_repos(1, []) == ["codehiro", "nethiro"]  # no task: any uncommitted files


def test_leftovers_are_what_no_task_there_owns(tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "ROOT", tmp_path)
    monkeypatch.setattr(hw, "REPOS", ["hiroleague", "codehiro", "nethiro", "homehiro"])
    monkeypatch.setattr(hw, "MAIN", {})
    for repo in ("hiroleague", "codehiro", "nethiro", "homehiro"):
        d = _repo(tmp_path / "env1" / repo, "one", "two")
        hw.git(d, "switch", "-q", "--detach", "main")  # as a free environment's repos are
    commit = ("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m")
    assert hw.leftovers(1, []) == []  # free, and every repo as it should be
    (tmp_path / "env1" / "codehiro" / "stray.txt").write_text("someone's", encoding="utf-8")
    hw.git(tmp_path / "env1" / "nethiro", "switch", "-q", "-c", "task/old")
    hw.git(tmp_path / "env1" / "nethiro", *commit, "kept")
    hw.git(tmp_path / "env1" / "homehiro", "switch", "-q", "--detach", "main~1")
    assert hw.leftovers(1, []) == [
        {"repo": "codehiro", "what": "1 uncommitted file"},
        {"repo": "nethiro", "what": "on branch task/old, 1 commit not on main"},
    ]  # homehiro is behind main: how a free environment sits until the next start, nothing left behind
    # With a task there, its reserves are its own and only another repo's uncommitted files are left over
    t = task("t", 1, ["codehiro", "nethiro"])
    (tmp_path / "env1" / "hiroleague" / "edit.txt").write_text("x", encoding="utf-8")
    assert hw.leftovers(1, [t]) == [{"repo": "hiroleague", "what": "1 uncommitted file"}]


def test_a_commit_needs_a_task_that_reserves_its_repo(tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "ROOT", tmp_path)
    monkeypatch.setattr(hw, "TASKS", tmp_path / "tasks")
    hw.TASKS.mkdir()
    folder = tmp_path / "env1" / "homehiro" / "backend"
    folder.mkdir(parents=True)
    with pytest.raises(hw.Stop, match="reserve <task> homehiro"):
        hw.cmd_fresh(type("A", (), {"path": str(folder)})())
    hw.save(task("t", 1, ["homehiro"]))
    hw.cmd_fresh(type("A", (), {"path": str(folder)})())  # reserved: the commit goes on
    hw.cmd_fresh(type("A", (), {"path": str(tmp_path / "elsewhere")})())  # not an environment's repo


def test_start_fetches_env0s_repos_side_by_side_as_one_timed_step(tmp_path, monkeypatch):
    read = _events(tmp_path, monkeypatch)
    monkeypatch.setattr(hw, "ROOT", tmp_path)
    for repo in ("codehiro", "nethiro"):
        origin = _repo(tmp_path / "origins" / repo, "one")
        hw.git(tmp_path, "clone", "-q", str(origin), str(tmp_path / "env0" / repo))
        hw.git(origin, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "two")
    hw.fetch_all(["codehiro", "nethiro", "studyhiro"], "t", 2)  # studyhiro has no checkout: its fetch fails quietly
    for repo in ("codehiro", "nethiro"):  # both fetched: origin's new commit is known, main itself untouched
        assert hw.git(tmp_path / "env0" / repo, "rev-list", "--count", "main..origin/main") == "1"
    steps = [e["step"] for e in read()]
    assert steps == ["fetch", "fetch"] and read()[-1]["ok"] is True  # one step, not one per repo


def test_reserve_adds_a_free_repo_and_refuses_one_held(tmp_path, monkeypatch):
    read = _events(tmp_path, monkeypatch)
    monkeypatch.setattr(hw, "ROOT", tmp_path)
    monkeypatch.setattr(hw, "TASKS", tmp_path / "tasks")
    hw.TASKS.mkdir()
    docs = _repo(tmp_path / "env1" / "hiro-docs", "one")
    monkeypatch.setattr(hw, "fresh_base", lambda repo, task: hw.git(docs, "rev-parse", "HEAD"))
    hw.save(task("t", 1, ["codehiro"]))
    hw.save(task("other", 1, ["nethiro"]))
    hw.cmd_reserve(type("A", (), {"task": "t", "repos": "hiro-docs", "kit": False})())
    t = hw.get("t")
    assert t.repos == ["codehiro", "hiro-docs"] and t.base["hiro-docs"]
    assert hw.git(docs, "branch", "--show-current") == "task/t"  # the reserved repo is on the task's branch
    assert read()[-1]["step"] == "reserve"
    with pytest.raises(hw.Stop, match="nethiro by other"):
        hw.cmd_reserve(type("A", (), {"task": "t", "repos": "nethiro", "kit": False})())


def test_env1_to_5_sign_in_as_env0_does_with_sends_and_has_automatic_writes_off():
    # AUTH None: env0's line (if any) is dropped and nothing is written, so the apps' sign-in is on and roles apply
    assert hw.ENV_DEV_FORCED == {"AUTH": None}
    assert hw.switches.app_env(hw.switches.resolve("Safe")) == {"OUTPUTS": "off", "HA_AUTO_WRITES": "off"}
    assert hw.switches.app_env(hw.switches.resolve("Full real")) == {"OUTPUTS": "on", "HA_AUTO_WRITES": "on"}


def test_sign_in_follows_the_task_and_finds_the_person_in_the_environments_own_list(tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "TASKS", tmp_path)
    monkeypatch.setattr(hw, "ROOT", tmp_path / "root")
    monkeypatch.setattr(hw, "people_of", lambda env: [{"id": "p2", "name": "Maro", "role": "Adult"}])
    assert hw.sign_in_of(2) == {"mode": "on"} and hw.sign_in_env(2) == {"AUTH": None}  # no task, no file
    hw.save(hw.Task(id="t", title="t", env=2, repos=["homehiro"], sign_in="off"))
    assert hw.sign_in_env(2) == {"AUTH": "off"} and hw.write_board(2)["sign_in"] == {"mode": "off"}
    hw.save(hw.Task(id="t", title="t", env=2, repos=["homehiro"], sign_in="as", sign_in_as="maro"))
    # as a person: the apps' sign-in stays on, and the core says who everyone is
    assert hw.sign_in_env(2) == {"AUTH": None}
    assert hw.write_board(2)["sign_in"] == {"mode": "as", "person": "p2", "name": "Maro"}
    hw.save(hw.Task(id="t", title="t", env=2, repos=["homehiro"], sign_in="as", sign_in_as="Nobody"))
    assert hw.write_board(2)["sign_in"] == {"mode": "on"}  # nobody found: never looser than asked


def test_an_environments_family_list_is_names_and_roles_only(tmp_path, monkeypatch):
    import sqlite3

    monkeypatch.setattr(hw, "ROOT", tmp_path)
    assert hw.people_of(2) == []  # no core database yet
    db = hw.data_dir(2) / "core" / "default" / "db" / "workspace.db"
    db.parent.mkdir(parents=True)
    con = sqlite3.connect(db)
    con.executescript("create table roles(role_id, name); create table people(person_id, name, role_id, whatsapp);"
                      "insert into roles values('kid','Kid'); insert into people values('p1','Mark','kid','+20100');"
                      "insert into people values('p0','Ana',null,null);")
    con.commit()
    con.close()
    assert hw.people_of(2) == [{"id": "p0", "name": "Ana", "role": ""}, {"id": "p1", "name": "Mark", "role": "Kid"}]


def test_an_environment_no_task_holds_reads_as_a_default_task_does(tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "TASKS", tmp_path)
    assert hw.real_of(0) == []  # env0 is real already
    monkeypatch.setattr(hw, "ROOT", tmp_path / "root")
    assert hw.real_of(2) == [hw.data.READS]  # no task, no file: the Safe preset
    hw.save(hw.Task(id="t", title="t", env=2, repos=["homehiro"], preset="Safe", switches={"ai": "real"}))
    assert hw.real_of(2) == [hw.data.READS, hw.data.AI]
    assert hw.write_board(2)["modes"]["ai"] == "real" and hw.switches.read(hw.data_dir(2))["changes"] == {"ai": "real"}
    hw.save(hw.Task(id="t", title="t", env=2, repos=["homehiro"], preset="Gone", switches={}))
    assert hw.modes_of(2) == hw.switches.resolve("Safe")  # a preset that is gone: the default


def test_merge_and_deploy_ignore_the_console_ctrl_c(monkeypatch):
    # onnxruntime's phantom Ctrl-C once killed a merge inside subprocess.run(check.sh)
    import signal

    before = signal.getsignal(signal.SIGINT)
    seen = {}
    monkeypatch.setattr(hw, "cmd_merge", lambda a: seen.setdefault("handler", signal.getsignal(signal.SIGINT)))
    try:
        assert hw.main(["merge", "some-task"]) == 0
        assert seen["handler"] == signal.SIG_IGN
        signal.raise_signal(signal.SIGINT)  # dropped: no KeyboardInterrupt
    finally:
        signal.signal(signal.SIGINT, before)


def test_other_commands_keep_ctrl_c(monkeypatch):
    import signal

    seen = {}
    monkeypatch.setattr(hw, "cmd_status", lambda a: seen.setdefault("handler", signal.getsignal(signal.SIGINT)))
    # Ctrl-C as a terminal gives it: the core's deploy runs the tests with SIGINT already ignored
    before = signal.signal(signal.SIGINT, signal.default_int_handler)
    try:
        assert hw.main(["status"]) == 0
    finally:
        signal.signal(signal.SIGINT, before)
    assert seen["handler"] == signal.default_int_handler
