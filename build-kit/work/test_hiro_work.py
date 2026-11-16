"""hiro-work's choices: the ports of an environment, what a task claims, where a new task goes."""

import json

import pytest

import hiro_work as hw


def task(id, env, repos, state="working"):
    return hw.Task(id=id, title=id, env=env, repos=repos, state=state)


def test_each_environment_owns_15_consecutive_ports():
    assert hw.ports(0)["core-admin"] == 7000
    assert hw.ports(2)["core-socket"] == 7201
    assert hw.ports(5)["codehiro-ui"] == 7512
    assert hw.ports(1)["core-plugin"] == 7114
    assert sorted(hw.ports(3).values()) == list(range(7300, 7315))


def test_claims_keep_the_core_first_and_a_kit_change_claims_the_apps():
    assert hw.expand(["homehiro", "hiroleague"], kit=False) == ["hiroleague", "homehiro"]
    assert hw.expand(["hiroleague"], kit=True) == ["hiroleague", "homehiro", "nethiro", "trainhiro", "studyhiro",
                                                    "codehiro"]
    with pytest.raises(hw.Stop):
        hw.expand(["nope"], kit=False)


def test_a_task_works_in_env0_while_its_repos_are_free_there():
    assert hw.pick_env(["homehiro"], [], None) == 0
    assert hw.pick_env(["homehiro"], [task("a", 0, ["nethiro"])], None) == 0


def test_a_task_goes_to_the_first_free_environment_when_env0_holds_a_repo():
    tasks = [task("a", 0, ["hiroleague", "homehiro"]), task("b", 1, ["nethiro"])]
    assert hw.pick_env(["homehiro"], tasks, None) == 2


def test_parked_and_finished_tasks_hold_nothing():
    tasks = [task("a", 0, ["homehiro"], state="parked"), task("b", None, ["homehiro"], state="parked")]
    assert hw.pick_env(["homehiro"], tasks, None) == 0


def test_asking_for_a_busy_place_is_refused():
    with pytest.raises(hw.Stop):
        hw.pick_env(["homehiro"], [task("a", 0, ["homehiro"])], 0)
    with pytest.raises(hw.Stop):
        hw.pick_env(["homehiro"], [task("a", 3, ["nethiro"])], 3)


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
    tasks = [task("a", 0, ["homehiro"])] + [task(f"t{e}", e, ["nethiro"]) for e in range(1, 6)]
    with pytest.raises(hw.Stop):
        hw.pick_env(["homehiro"], tasks, None)


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
    with hw.step("t", 1, "land"):
        with hw.step("t", 1, "check", "codehiro"):
            pass
    with hw.step("t", 1, "after"):
        pass
    by = {(e["step"], e["phase"]): e for e in read()}
    assert "parent" not in by[("land", "start")]
    assert by[("check", "start")]["parent"] == "land" and by[("check", "end")]["parent"] == "land"
    assert "parent" not in by[("after", "start")]


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


def test_review_marks_a_working_task_and_refuses_a_parked_one(tmp_path, monkeypatch):
    read = _events(tmp_path, monkeypatch)
    monkeypatch.setattr(hw, "TASKS", tmp_path / "tasks")
    hw.TASKS.mkdir()
    hw.save(task("t", 1, ["codehiro"]))
    hw.cmd_review(type("A", (), {"task": "t"})())
    assert read()[-1] == {**read()[-1], "task": "t", "env": 1, "step": "review", "phase": "start"}
    hw.save(task("p", None, ["codehiro"], state="parked"))
    with pytest.raises(hw.Stop):
        hw.cmd_review(type("A", (), {"task": "p"})())


def test_sweep_leaves_out_branches_in_use():
    listing = "* dev\n+ task/open-one\n  task/old\n  main\n  (HEAD detached at 1234)\n"
    assert hw.merged_left(listing, "dev") == ["task/old"]


def test_a_land_records_the_commits_it_added(tmp_path, monkeypatch):
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
    hw.record_commits("t", 1, "codehiro", before, after, "land")
    hw.record_commits("t", 1, "codehiro", after, after, "land")  # nothing new: no event
    [e] = read()
    assert (e["step"], e["how"], e["from"], e["to"], len(e["commits"])) == ("commits", "land", before, after, 2)
    assert e["commits"][0] == after


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
