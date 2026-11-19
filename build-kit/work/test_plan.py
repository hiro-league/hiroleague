"""hiro-work plan: a plan's phases as one Work event, checked before it is written, read back from the same log."""

import json

import pytest

import hiro_work as hw
import plan


@pytest.fixture
def log(tmp_path, monkeypatch):
    """A log of its own: a test's events never reach the sender."""
    monkeypatch.setattr(hw, "LOGS", tmp_path / "logs")
    monkeypatch.setattr(hw, "EVENTS", tmp_path / "logs" / "events.jsonl")
    return tmp_path


def a_plan(**more):
    return {
        "name": "Chores board",
        "doc": "https://claude.ai/artifact/LQVoaS4SrcvmowbGxiHi3g",
        "phases": [
            {"name": "Mockup of the board", "state": "live"},
            {"name": "Kids tick them off", "state": "review", "needs": "1", "tasks": ["chores-tick"]},
            {"name": "Points and rewards", "state": "waits", "says": "Waits on Q2", "needs": "2, Q2"},
        ],
    } | more


def send(tmp_path, body) -> int:
    file = tmp_path / "plan.json"
    file.write_text(json.dumps(body), encoding="utf-8")
    return hw.main(["plan", "send", str(file)])


def events(tmp_path) -> list[dict]:
    path = tmp_path / "logs" / "events.jsonl"
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def test_a_send_is_one_event_holding_the_whole_plan(log):
    assert send(log, a_plan(needs_michel="  Answer   Q2 ", tasks=["chores-board"])) == 0
    (e,) = events(log)
    assert (e["step"], e["phase"], e["task"], e["plan"]) == ("plan-sent", "end", None, "Chores board")
    assert e["needs_michel"] == "Answer Q2"  # spaces tidied
    assert e["tasks"] == ["chores-board"]
    assert e["phases"][1] == {"name": "Kids tick them off", "state": "review", "says": "", "needs": "1",
                              "tasks": ["chores-tick"]}


@pytest.mark.parametrize(
    "broken, says",
    [
        (a_plan(doc="http://example.com/x"), "Claude Doc"),
        (a_plan(name=" "), "name is missing"),
        (a_plan(phases=[]), "1 to 12 phases"),
        (a_plan(phases=[{"name": "A", "state": "done"}]), "its state must be one of"),
        (a_plan(phases=[{"name": "A", "state": "live", "tasks": ["Not An Id"]}]), "task ids"),
        (a_plan(status="x"), "Not a plan's field: status"),
    ],
)
def test_a_wrong_plan_is_refused_and_nothing_is_written(log, capsys, broken, says):
    assert send(log, broken) == 1
    assert says in capsys.readouterr().out
    assert events(log) == []


def test_the_latest_send_of_a_plan_is_the_plan(log, capsys):
    send(log, a_plan())
    later = a_plan()
    later["phases"][1]["state"] = "live"
    send(log, later | {"name": "chores BOARD"})  # the same plan: its name in other letters
    send(log, a_plan(name="Other work"))
    capsys.readouterr()

    assert hw.main(["plan", "list"]) == 0
    listed = capsys.readouterr().out.splitlines()
    assert [x.split(":")[0] for x in listed] == ["Other work", "chores BOARD"]
    assert "2 of 3 phases live" in listed[1]

    assert hw.main(["plan", "show", "Chores board"]) == 0
    shown = capsys.readouterr().out
    assert "2. Kids tick them off: live (needs 1; tasks chores-tick)" in shown
    assert "3. Points and rewards: waits (Waits on Q2; needs 2, Q2)" in shown
    assert hw.main(["plan", "show", "nothing"]) == 1
