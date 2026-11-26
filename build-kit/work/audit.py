r"""hiro-work audit: the doc audit's runs, recorded for CodeHiro's Work › Hiro-Audit and read back in Claude.

The doc audit (hiro-docs standards/doc-audit.md, the /hiro-doc-audit skill) records each run as two Work events,
through the same outbox as every step (C:\hiro\logs\events.jsonl, sent by ship.py):

    hiro-work audit start [--scope S]   a run begins: its id, and the repos with new commits since the last run
                                        (doc-audit-state.json, each repo's recorded commit to its branch's tip)
    hiro-work audit report RUN FILE     the run's report, the Markdown exactly as Claude wrote it

A run is a snapshot: nothing in it changes afterwards. Read back from the same log, so Claude needs nothing else:

    hiro-work audit latest              the latest reported run's report
    hiro-work audit RUN                 one run's report
    hiro-work audit list                every run: when, its state, its repos

CodeHiro's Run audit asks the PC's helper (relay.py), which opens Claude on /hiro-doc-audit in the hiro-audit window.
Standard library only.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import hiro_work as hw

STATE = hw.ROOT / "env0" / "hiro-docs" / "standards" / "doc-audit-state.json"
STEP = "audit"
# A report longer than this can't go as one event (CodeHiro takes an audit event up to 200,000 characters)
MAX_REPORT = 190_000
# A run started this long ago with no report is shown as stopped: Claude was closed before it reported
STALE_S = 12 * 3600


def run_id(now: datetime) -> str:
    return now.strftime("%Y-%m-%d-%H%M")


def new_commits(state: dict, scope: str) -> list[dict]:
    """Each repo the run covers and its new commits since its recorded one, on its own branch (GitHub's tip when the
    repo has fetched it, else the local branch). ``scope``: "since the last run" (the repos with new commits),
    "full" (every repo) or one repo's name."""
    out = []
    for repo, r in (state.get("repos") or {}).items():
        if scope not in ("since the last run", "full") and repo != scope:
            continue
        path, branch, commit = Path(r["path"]), r["branch"], r["commit"]
        tip = f"origin/{branch}" if hw.git(path, "rev-parse", "--verify", "-q", f"origin/{branch}",
                                           check=False) else branch
        count = hw.git(path, "rev-list", "--count", f"{commit}..{tip}", check=False)
        n = int(count) if count.isdigit() else 0
        if n or scope != "since the last run":
            out.append({"repo": repo, "commits": n})
    return out


def runs(lines: list[dict], now: float | None = None) -> list[dict]:
    """Every run in the log, the latest first: id, started, ended, state (running | reported | stopped), scope, repos,
    and its report (None until it reports)."""
    now = time.time() if now is None else now
    by_id: dict[str, dict] = {}
    for e in lines:
        if e.get("step") != STEP or not e.get("run"):
            continue
        rid = str(e["run"])
        if e.get("phase") == "start":
            by_id[rid] = {"id": rid, "started": e.get("at"), "ended": None, "state": "running",
                          "scope": e.get("scope") or "since the last run", "repos": e.get("repos") or [],
                          "report": None}
        elif e.get("phase") == "end" and rid in by_id:
            by_id[rid].update(ended=e.get("at"), state="reported", report=e.get("report") or "")
    out = sorted(by_id.values(), key=lambda r: r["started"] or "", reverse=True)
    for i, r in enumerate(out):
        if r["state"] != "running":
            continue
        started = datetime.fromisoformat(r["started"]).timestamp() if r["started"] else 0
        if i > 0 or now - started > STALE_S:  # a newer run began, or too long without a report
            r["state"] = "stopped"
    return out


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


def when(iso: str | None) -> str:
    """A run's time as Michel reads it: the day and a 12-hour clock."""
    if not iso:
        return "—"
    t = datetime.fromisoformat(iso).astimezone()
    today = datetime.now().astimezone().date()
    day = {0: "Today", 1: "Yesterday"}.get((today - t.date()).days)
    day = day or (t.strftime("%a, %b ") + str(t.day) + (f", {t.year}" if t.year != today.year else ""))
    return f"{day}, {t.strftime('%I:%M %p').lstrip('0')}"


def cmd_start(a) -> None:
    if not STATE.exists():
        raise hw.Stop(f"No {STATE}: the audit's state file is where the last run's commits are.")
    state = json.loads(STATE.read_text(encoding="utf-8"))
    repos = new_commits(state, a.scope)
    rid = run_id(datetime.now())
    hw.event(task=None, env=None, step=STEP, phase="start", run=rid, scope=a.scope, repos=repos)
    hw.say(f"Audit run {rid} ({a.scope}), recorded.")
    for r in repos:
        hw.say(f"  {r['repo']}: {r['commits']} new commit(s)")
    if not repos:
        hw.say("  No repo has new commits since the last run.")
    hw.say(f"When it reports: hiro-work audit report {rid} <the report's .md file>")


def cmd_report(a) -> None:
    lines = read_log(hw.EVENTS)
    run = next((r for r in runs(lines) if r["id"] == a.run), None)
    if not run:
        raise hw.Stop(f"No audit run {a.run} (hiro-work audit list).")
    if run["state"] == "reported":
        raise hw.Stop(f"Run {a.run} has its report already: a run is a snapshot.")
    report = Path(a.file).read_text(encoding="utf-8").strip()
    if not report:
        raise hw.Stop(f"{a.file} is empty.")
    if len(report) > MAX_REPORT:
        raise hw.Stop(f"The report is {len(report):,} characters; one event takes at most {MAX_REPORT:,}.")
    started = datetime.fromisoformat(run["started"]).timestamp() if run["started"] else time.time()
    hw.event(task=None, env=None, step=STEP, phase="end", ok=True, run=a.run, seconds=round(time.time() - started),
             report=report)
    hw.say(f"Audit run {a.run}: its report is recorded ({len(report):,} characters). CodeHiro's Work › Hiro-Audit "
           f"shows it once the sender delivers it.")


def cmd_show(a) -> None:
    all_runs = runs(read_log(hw.EVENTS))
    if a.what == "list":
        if not all_runs:
            hw.say("No audit run is recorded yet.")
        for r in all_runs:
            repos = ", ".join(f"{x['repo']} ({x['commits']})" for x in r["repos"]) or "no new commits"
            hw.say(f"{r['id']}  {when(r['started'])}  {r['state']}  {r['scope']}: {repos}")
        return
    if a.what == "latest":
        run = next((r for r in all_runs if r["state"] == "reported"), None)
        if not run:
            raise hw.Stop("No audit run has reported yet.")
    else:
        run = next((r for r in all_runs if r["id"] == a.what), None)
        if not run:
            raise hw.Stop(f"No audit run {a.what} (hiro-work audit list).")
        if run["state"] != "reported":
            raise hw.Stop(f"Run {a.what} is {run['state']}: it has no report.")
    repos = ", ".join(f"{x['repo']} ({x['commits']})" for x in run["repos"]) or "no new commits"
    hw.say(f"Audit run {run['id']}: started {when(run['started'])}, reported {when(run['ended'])}; "
           f"{run['scope']}: {repos}\n")
    hw.say(run["report"])


def cmd_audit(a) -> None:
    if a.what == "start":
        cmd_start(a)
    elif a.what == "report":
        if not (a.run and a.file):
            raise hw.Stop("hiro-work audit report RUN FILE")
        cmd_report(a)
    else:
        cmd_show(a)


def add_parser(sub) -> None:
    p = sub.add_parser("audit", help="the doc audit's runs: start, report, list, latest or a run's id",
                       formatter_class=argparse.RawDescriptionHelpFormatter, description=__doc__.split("\n\n")[1])
    p.add_argument("what", help="start, report, list, latest, or a run's id")
    p.add_argument("run", nargs="?", help="report: the run's id")
    p.add_argument("file", nargs="?", help="report: the report's Markdown file")
    p.add_argument("--scope", default="since the last run", help="start: 'full', or one repo's name")
    p.set_defaults(func=cmd_audit)
