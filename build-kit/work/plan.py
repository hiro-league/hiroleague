r"""hiro-work plan: a plan's phases and their states, sent to CodeHiro's Work area.

A plan lives in a Claude Doc (hiro-docs standards/plans.md), which CodeHiro can't read. So whenever the plan's phases
change, the session sends them, through the same outbox as every step (C:\hiro\logs\events.jsonl, sent by ship.py):

    hiro-work plan send FILE      the plan as it stands now, from a JSON file (below): one event, the whole plan
    hiro-work plan list           every plan sent: its phases live, and when it was last sent
    hiro-work plan show NAME      a plan as last sent

Each send is the whole plan, never a change to it: CodeHiro shows the latest, and works out what changed between two
sends. A plan belongs to tasks by its name: every task started with ``--part-of "<name>"`` shows it, and so does each
task the file names. The file:

    {"name": "Chores board",                        the work's name, as tasks say it in --part-of
     "doc": "https://claude.ai/artifact/...",       the plan doc
     "about": "A board where the kids tick chores", optional: what the plan is for, in a sentence
     "tasks": ["chores-board"],                     optional: tasks that are this plan's, by id
     "needs_michel": "Answer Q2",                   optional: what waits on Michel
     "side_by_side": "Phases 3 and 4",              optional: what can run at the same time
     "phases": [{"name": "Mockup of the board",     in the plan's order
                 "state": "live",                   live | check | merged | working | review | next | waits | todo
                 "says": "",                        optional: the state in the plan's words ("Waits on Q2")
                 "needs": "1, Q2",                  optional: what it needs first
                 "tasks": ["chores-mockup"]}]}      optional: the tasks that work on this phase, by id

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import hiro_work as hw
from audit import when

# Not "plan": that is a deploy's own step, and CodeHiro reads a step by its name
STEP = "plan-sent"
# A phase's states, as plans.md's key names them: live, live with a check left, merged and not deployed, being
# worked on, in review, next, waits on a decision, not started
STATES = ("live", "check", "merged", "working", "review", "next", "waits", "todo")
SHIPPED = ("live", "check")
MAX_PHASES = 12
MAX_WORDS = 200
TASK_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
DOC = re.compile(r"^https://claude\.ai/[\w./?=&%#-]{1,300}$")


def words(raw: object, what: str, most: int = MAX_WORDS, needed: bool = False) -> str:
    if raw is None and not needed:
        return ""
    if not isinstance(raw, str):
        raise hw.Stop(f"{what} must be text.")
    text = " ".join(raw.split())
    if needed and not text:
        raise hw.Stop(f"{what} is missing.")
    if len(text) > most:
        raise hw.Stop(f"{what} is {len(text)} characters; at most {most}.")
    return text


def task_ids(raw: object, what: str) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(t, str) and TASK_ID.match(t) for t in raw):
        raise hw.Stop(f"{what} must be a list of task ids (as hiro-work start names them).")
    return list(dict.fromkeys(raw))


def checked(raw: object) -> dict:
    """The plan a file holds, as the event carries it; Stop names the first thing wrong."""
    if not isinstance(raw, dict):
        raise hw.Stop("The file must hold one plan: a JSON object (hiro-work plan --help).")
    unknown = sorted(set(raw) - {"name", "doc", "about", "tasks", "needs_michel", "side_by_side", "phases"})
    if unknown:
        raise hw.Stop(f"Not a plan's field: {', '.join(unknown)}.")
    doc = words(raw.get("doc"), "The plan's doc", 320, needed=True)
    if not DOC.match(doc):
        raise hw.Stop("The plan's doc must be its Claude Doc's link (https://claude.ai/...).")
    phases = raw.get("phases")
    if not isinstance(phases, list) or not 1 <= len(phases) <= MAX_PHASES:
        raise hw.Stop(f"A plan has 1 to {MAX_PHASES} phases.")
    out = []
    for i, p in enumerate(phases, 1):
        if not isinstance(p, dict):
            raise hw.Stop(f"Phase {i} must be an object.")
        unknown = sorted(set(p) - {"name", "state", "says", "needs", "tasks"})
        if unknown:
            raise hw.Stop(f"Phase {i}: not a phase's field: {', '.join(unknown)}.")
        if p.get("state") not in STATES:
            raise hw.Stop(f"Phase {i}: its state must be one of {', '.join(STATES)}.")
        out.append({
            "name": words(p.get("name"), f"Phase {i}'s name", 80, needed=True),
            "state": p["state"],
            "says": words(p.get("says"), f"Phase {i}'s says", 60),
            "needs": words(p.get("needs"), f"Phase {i}'s needs", 60),
            "tasks": task_ids(p.get("tasks"), f"Phase {i}'s tasks"),
        })
    return {
        "plan": words(raw.get("name"), "The plan's name", 80, needed=True),
        "doc": doc,
        "about": words(raw.get("about"), "The plan's about", 300),
        "tasks": task_ids(raw.get("tasks"), "The plan's tasks"),
        "needs_michel": words(raw.get("needs_michel"), "needs_michel"),
        "side_by_side": words(raw.get("side_by_side"), "side_by_side"),
        "phases": out,
    }


def plans(lines: list[dict]) -> list[dict]:
    """Every plan in the log as last sent, the latest sent first."""
    latest: dict[str, dict] = {}
    for e in lines:
        if e.get("step") == STEP and e.get("plan") and isinstance(e.get("phases"), list):
            latest.pop(str(e["plan"]).casefold(), None)  # a later send moves the plan to the end
            latest[str(e["plan"]).casefold()] = e
    return list(latest.values())[::-1]


def read_log(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if f'"{STEP}"' not in raw:
            continue  # most lines are other steps: skip them unparsed
        try:
            line = json.loads(raw)
        except ValueError:
            continue
        if isinstance(line, dict):
            out.append(line)
    return out


def shipped(plan: dict) -> str:
    done = sum(1 for p in plan["phases"] if p.get("state") in SHIPPED)
    return f"{done} of {len(plan['phases'])} phases live"


def cmd_send(a) -> None:
    if not a.name:
        raise hw.Stop("hiro-work plan send FILE")
    try:
        raw = json.loads(Path(a.name).read_text(encoding="utf-8"))
    except OSError as exc:
        raise hw.Stop(f"Can't read {a.name}: {exc.strerror or exc}.") from exc
    except ValueError as exc:
        raise hw.Stop(f"{a.name} isn't JSON: {exc}.") from exc
    plan = checked(raw)
    hw.event(task=None, env=None, step=STEP, phase="end", ok=True, **plan)
    hw.say(f"Plan {plan['plan']}: {shipped(plan)}, recorded. CodeHiro's Work area shows it once the sender delivers it.")


def cmd_show(a) -> None:
    every = plans(read_log(hw.EVENTS))
    if a.what == "list":
        if not every:
            hw.say("No plan has been sent yet.")
        for p in every:
            hw.say(f"{p['plan']}: {shipped(p)}, sent {when(p.get('at'))}")
        return
    if not a.name:
        raise hw.Stop("hiro-work plan show NAME")
    plan = next((p for p in every if str(p["plan"]).casefold() == a.name.casefold()), None)
    if not plan:
        raise hw.Stop(f"No plan {a.name} (hiro-work plan list).")
    hw.say(f"{plan['plan']}: {shipped(plan)}, sent {when(plan.get('at'))}\n{plan.get('doc')}")
    for i, p in enumerate(plan["phases"], 1):
        more = "; ".join(x for x in (p.get("says"), f"needs {p['needs']}" if p.get("needs") else "",
                                     f"tasks {', '.join(p['tasks'])}" if p.get("tasks") else "") if x)
        hw.say(f"  {i}. {p['name']}: {p['state']}" + (f" ({more})" if more else ""))
    for label, key in (("Needs Michel", "needs_michel"), ("Side by side", "side_by_side")):
        if plan.get(key):
            hw.say(f"{label}: {plan[key]}")


def cmd_plan(a) -> None:
    # A plan's words hold › and —: a Windows console's own code page would print them as ?
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if a.what == "send":
        cmd_send(a)
    elif a.what in ("list", "show"):
        cmd_show(a)
    else:
        raise hw.Stop("hiro-work plan send FILE | list | show NAME")


def add_parser(sub) -> None:
    p = sub.add_parser("plan", help="a plan's phases, sent to CodeHiro: send FILE, list, show NAME",
                       formatter_class=argparse.RawDescriptionHelpFormatter,
                       description=__doc__.split("\n\n", 1)[1].rsplit("\n\n", 1)[0])
    p.add_argument("what", help="send, list or show")
    p.add_argument("name", nargs="?", help="send: the plan's JSON file; show: the plan's name")
    p.set_defaults(func=cmd_plan)
