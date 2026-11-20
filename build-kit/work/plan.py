r"""hiro-work plan: a plan's phases and their states, sent to CodeHiro's Work area.

A plan lives in a Claude Doc (hiro-docs standards/plans.md), which CodeHiro can't read. So whenever the plan's phases
change, the session sends them, through the same outbox as every step (C:\hiro\logs\events.jsonl, sent by ship.py):

    hiro-work plan send FILE [--remove PHASE]...
                                  the plan as it stands now, from a JSON file (below): one event, the whole plan
    hiro-work plan list           every plan sent: its phases live, and when it was last sent
    hiro-work plan show NAME      a plan as last sent
    hiro-work plan close NAME     the plan stops here: its open tasks are cancelled, its phases not done yet too

Each send is the whole plan, never a change to it: CodeHiro shows the latest, and works out what changed between two
sends. A send never drops by accident a phase that is live, merged or has tasks: one the last send had and this one
leaves out (a rename or a split leaves one out too) is refused unless named with --remove.

A plan ends when every phase is live or cancelled. Its phases follow its tasks (hiro-work pause, resume, cancel and
reopen send it again): a task paused puts its phase in paused, resumed back in working; a task cancelled puts it back
in next, since the work is still to do, and the plan goes on. Only closing the plan cancels its phases; one live stays
live. A closed plan opens again with a send that has a phase not live or cancelled. A plan belongs to tasks by its name: every task started with ``--part-of "<name>"`` shows it, and so does each
task the file names. The file:

    {"name": "Chores board",                        the work's name, as tasks say it in --part-of
     "doc": "https://claude.ai/artifact/...",       the plan doc
     "design": "https://claude.ai/artifact/...",    optional: the plan's design doc, when it made one
     "about": "A board where the kids tick chores", optional: what the plan is for, in a sentence
     "tasks": ["chores-board"],                     optional: tasks that are this plan's, by id
     "needs_michel": "Answer Q2",                   optional: what waits on Michel
     "side_by_side": "Phases 3 and 4",              optional: what can run at the same time
     "ships": "whole",                              optional: "whole", the plan ships whole on its own branch
                                                    (plan/<name>: its phases merge into it, it reaches main when it
                                                    lands); left out, "phases": each phase merges into main
     "phases": [{"name": "Mockup of the board",     in the plan's order
                 "state": "live",                   live | check | merged | working | review | paused | next | waits |
                                                    todo | cancelled
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
STATES = ("live", "check", "merged", "working", "review", "paused", "next", "waits", "todo", "cancelled")
SHIPPED = ("live", "check")
# A phase in one of these is finished: the plan ends when all are
FINAL = (*SHIPPED, "cancelled")
# A phase in one of these holds work a send must not drop by accident (it has tasks too)
KEPT = (*SHIPPED, "merged")
# How a phase's state reads in hiro-work's own lines
SAYS = {"next": "Next", "paused": "Paused", "working": "Being worked on", "cancelled": "Cancelled"}
# The plan's fields a send carries, besides its phases (a resend keeps them: a pause keeps the plan's branch)
FIELDS = ("doc", "design", "about", "tasks", "needs_michel", "side_by_side", "ships", "branch")
# How a plan ships: phase by phase into main (the default), or whole, on its own branch
SHIPS = ("whole", "phases")
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
    unknown = sorted(set(raw) - {"name", "doc", "design", "about", "tasks", "needs_michel", "side_by_side", "ships",
                                 "phases"})
    if unknown:
        raise hw.Stop(f"Not a plan's field: {', '.join(unknown)}.")
    doc = words(raw.get("doc"), "The plan's doc", 320, needed=True)
    if not DOC.match(doc):
        raise hw.Stop("The plan's doc must be its Claude Doc's link (https://claude.ai/...).")
    design = words(raw.get("design"), "The plan's design doc", 320)
    if design and not DOC.match(design):
        raise hw.Stop("The plan's design doc must be its Claude Doc's link (https://claude.ai/...).")
    ships = raw.get("ships") or "phases"
    if ships not in SHIPS:
        raise hw.Stop('The plan\'s ships must be "whole" (on its own branch) or "phases" (each into main).')
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
    name = words(raw.get("name"), "The plan's name", 80, needed=True)
    return {
        "plan": name,
        "doc": doc,
        "design": design,
        "about": words(raw.get("about"), "The plan's about", 300),
        "tasks": task_ids(raw.get("tasks"), "The plan's tasks"),
        "needs_michel": words(raw.get("needs_michel"), "needs_michel"),
        "side_by_side": words(raw.get("side_by_side"), "side_by_side"),
        "ships": ships,
        "branch": branch_name(name) if ships == "whole" else "",
        "phases": out,
    }


def branch_name(name: str) -> str:
    """A plan's branch, the same in every repo: its name in lower case, each run of other characters than a-z0-9 a
    "-", under plan/ ("Logging and tracing" is plan/logging-and-tracing)."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not slug:
        raise hw.Stop(f"Plan {name}: its name gives no branch name (it needs a letter or a digit).")
    return f"plan/{slug}"


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


def latest(name: str) -> dict | None:
    """The plan as last sent, by its name."""
    return next((p for p in plans(read_log(hw.EVENTS)) if str(p["plan"]).casefold() == name.casefold()), None)


def branch_of(name: str) -> str:
    """The plan's branch when it ships whole, as last sent; "" for a plan that ships phase by phase, or no plan."""
    p = latest(name) if name else None
    return str(p.get("branch") or "") if p and p.get("ships") == "whole" else ""


def ships_guard(old: dict | None, new: dict) -> list[str]:
    """Stop a send that would lose a plan's branch or share one: two plans whose names give one branch name (G5), or
    "whole" turned off while the branch holds work main lacks, or an open task works on it (G4: land it or close it
    first). Turned off with nothing on it, the branch goes: it exists only while it holds work. Returns the repos whose
    branch went."""
    if new["ships"] == "whole":
        other = next((p for p in plans(read_log(hw.EVENTS)) if p.get("ships") == "whole" and p.get("branch") ==
                      new["branch"] and str(p["plan"]).casefold() != new["plan"].casefold()), None)
        if other:
            raise hw.Stop(f"Plan {new['plan']}: its branch would be {new['branch']}, which is plan {other['plan']}'s. "
                          "Give it a name that differs in its letters or digits.")
        return []
    if not old or old.get("ships") != "whole" or not old.get("branch"):
        return []
    branch = old["branch"]
    held = [r for r in hw.REPOS if hw.branch_tip(r, branch) and hw.git(
        hw.repo_dir(0, r), "rev-list", "--count", f"{hw.main_of(r)}..{branch}") != "0"]
    working = [t.id for t in hw.load_tasks() if t.state in ("working", "paused") and t.target == branch]
    if held or working:
        what = "; ".join(x for x in (f"it holds work main lacks in {', '.join(held)}" if held else "",
                                     f"open tasks work on it: {', '.join(working)}" if working else "") if x)
        raise hw.Stop(f"Plan {new['plan']} ships whole on {branch}, and {what}. It can't turn to phase by phase: land "
                      "it or close it first.")
    gone = []
    for r in hw.REPOS:
        if at := hw.branch_tip(r, branch):
            hw.git(hw.repo_dir(0, r), "update-ref", "-d", f"refs/heads/{branch}", at)
            gone.append(r)
    return gone


def guard(old: dict | None, new: dict, removing: list[str]) -> None:
    """Stop a send that leaves out a phase the last send had that is live, merged or has tasks, unless --remove names
    it: its work and history would leave CodeHiro's page by accident."""
    if not old:
        return
    kept = {str(p["name"]).casefold() for p in new["phases"]} | {r.casefold() for r in removing}
    lost = [p for p in old.get("phases") or [] if isinstance(p, dict) and str(p.get("name", "")).casefold() not in kept
            and (p.get("state") in KEPT or p.get("tasks"))]
    if lost:
        named = ", ".join(f'"{p["name"]}" ({p["state"]}' + (f", tasks {', '.join(p['tasks'])})" if p.get("tasks") else ")")
                          for p in lost)
        flags = " ".join(f'--remove "{p["name"]}"' for p in lost)
        raise hw.Stop(f"Plan {new['plan']}: this send leaves out {named}. A send never drops a live, merged or worked-on "
                      f"phase by accident. If you mean it (renamed, split, moved), send it again with {flags}.")


def resend(old: dict, phases: list[dict]) -> None:
    """The plan sent again with new phases, the rest as last sent."""
    hw.event(task=None, env=None, step=STEP, phase="end", ok=True, plan=old["plan"],
             **{k: old.get(k) or ("" if k != "tasks" else []) for k in FIELDS}, phases=phases)


def follow(task_id: str, to: str, when: tuple[str, ...], others: set[str]) -> list[str]:
    """CodeHiro's copy of each plan naming the task follows it: each phase the task works on whose state is in
    ``when``, and that no other task in ``others`` (the open ones) works on, moves to ``to``, its own words cleared.
    Returns one line per plan that moved, telling the session to update the plan doc."""
    out = []
    for plan in plans(read_log(hw.EVENTS)):
        moved, phases = [], []
        for i, ph in enumerate(plan["phases"], 1):
            ph = dict(ph)
            tasks = set(ph.get("tasks") or [])
            if task_id in tasks and ph.get("state") in when and not (tasks - {task_id}) & others:
                ph["state"], ph["says"] = to, ""
                moved.append(f"phase {i} ({ph['name']})")
            phases.append(ph)
        if moved:
            resend(plan, phases)
            out.append(f"Plan {plan['plan']}: {', '.join(moved)} now {SAYS.get(to, to)} in CodeHiro. Update the plan doc "
                       "to match.")
    return out


def cmd_close(a) -> None:
    """The plan stops here: its open tasks are cancelled (none moves until each can be), its phases not finished are
    cancelled; live ones stay live, merged ones wait for the deploy. It ends once all are live or cancelled."""
    if not a.name:
        raise hw.Stop("hiro-work plan close NAME")
    plan = latest(a.name)
    if not plan:
        raise hw.Stop(f"No plan {a.name} (hiro-work plan list).")
    named = set(plan.get("tasks") or []) | {t for ph in plan["phases"] for t in ph.get("tasks") or []}
    tasks = [t for t in hw.load_tasks() if t.state in ("working", "paused")
             and (t.id in named or t.part_of.casefold() == str(plan["plan"]).casefold())]
    for t in tasks:
        hw.can_cancel(t)
    for t in tasks:
        hw.cancel_task(t)
    phases = [{**ph, "state": "cancelled", "says": ""} if ph.get("state") not in (*FINAL, "merged") else dict(ph)
              for ph in plan["phases"]]
    resend(plan, phases)
    count = {s: sum(1 for ph in phases if ph["state"] in s) for s in (SHIPPED, ("cancelled",), ("merged",))}
    waits = f", {count[('merged',)]} merged (it ends once they are live)" if count[("merged",)] else ""
    hw.say(f"Plan {plan['plan']} closed: {count[SHIPPED]} live, {count[('cancelled',)]} cancelled{waits}. Update the "
           "plan doc to match (a closed plan opens again with a send that has a phase still to do).")


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
    old = latest(plan["plan"])
    guard(old, plan, a.remove or [])
    gone = ships_guard(old, plan)
    hw.event(task=None, env=None, step=STEP, phase="end", ok=True, **plan)
    whole = f", ships whole on {plan['branch']}" if plan["branch"] else ""
    hw.say(f"Plan {plan['plan']}: {shipped(plan)}{whole}, recorded. CodeHiro's Work area shows it once the sender "
           "delivers it.")
    if gone:
        hw.say(f"  {old['branch']} held nothing main lacks: removed from {', '.join(gone)}.")


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
    if plan.get("ships") == "whole":
        hw.say(f"Ships whole on {plan.get('branch')}: its phases merge into it, and it reaches main when it lands.")
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
    elif a.what == "close":
        cmd_close(a)
    else:
        raise hw.Stop("hiro-work plan send FILE | list | show NAME | close NAME")


def add_parser(sub) -> None:
    p = sub.add_parser("plan", help="a plan's phases, sent to CodeHiro: send FILE, list, show NAME, close NAME",
                       formatter_class=argparse.RawDescriptionHelpFormatter,
                       description=__doc__.split("\n\n", 1)[1].rsplit("\n\n", 1)[0])
    p.add_argument("what", help="send, list, show or close")
    p.add_argument("name", nargs="?", help="send: the plan's JSON file; show, close: the plan's name")
    p.add_argument("--remove", action="append", metavar="PHASE",
                   help="send: a phase the last send had that this one leaves out on purpose (once per phase)")
    p.set_defaults(func=cmd_plan)
