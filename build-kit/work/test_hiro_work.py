"""hiro-work's choices: the ports of an environment, what a task claims, where a new task goes."""

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
    assert sorted(configs) == sorted(["hiroleague", *hw.APPS])  # codehiro and aicam have no servers in the table
    assert [c["name"] for c in configs["hiroleague"]] == ["core", "core-ui"]
    ports = [c["port"] for repo in configs.values() for c in repo]
    p = hw.ports(3)  # the core's server is its admin API; its other listeners come with it
    apps = [p[f"{a}-{side}"] for a in hw.APPS for side in ("api", "ui")]
    assert sorted(ports) == sorted([p["core-admin"], p["core-ui"], *apps])
    homehiro_api = configs["homehiro"][0]
    assert homehiro_api["runtimeExecutable"] == "powershell"
    script = hw.Path(homehiro_api["runtimeArgs"][-1])  # the same runner as `hiro-work up`: reads .env.dev
    assert script.exists() and ".env.dev" in script.read_text(encoding="utf-8-sig")
