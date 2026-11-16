r"""hiro-work train: the deploy train (hiro-docs standards/building-and-releasing.md, "Commit, push, deploy").

One run, started when Michel says, ships everything committed since the last one:

    hiro-work train [repo ...] [--dry-run] [--yes]

1. The plan: for each repo, what GitHub lacks (origin's branch..dev/main) and what live lacks (the server's
   commit..dev/main; aicam: ~/aicam's commit on Simone), shown before anything moves. A repo whose GitHub or server
   has commits this PC lacks stops the whole train here: nothing is ever forced.
2. A go: the question, or --yes.
3. Push: every repo with new commits to GitHub, side by side (a plain push, which git refuses unless it fast-forwards).
4. Deploy: the core first when live lacks something (its own hook: `git push server dev:main`), then the apps and aicam
   side by side (`git push server main`; aicam: then `git -C ~/aicam pull --ff-only` on Simone, and which service may
   need a restart: the train never restarts one). Each deploy's own safety (database copies, migration trials, going
   back by itself) is the hook's, untouched here. A failed core deploy stops the apps.
5. Verify each (it answers; no new errors in its log since its deploy started), then one report.

Without --dry-run, it runs in a Windows Terminal window of its own ("hiro-train") so Michel watches it; the window
asks the question. Every step is timed into C:\hiro\logs\events.jsonl (task "train-<time>", kind "deploy"), and the
window's whole output is kept in C:\hiro\logs\train\<task>.log.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import hiro_work as hw
from stages import Stages

# How each repo goes live (the standard's table). hiro-docs only goes to GitHub here: publishing its site (dev merged
# into main, then the mintdocs policy script) stays a step of its own.
CORE, APP, AICAM = "core", "app", "aicam"
DEPLOY = {"hiroleague": CORE, "homehiro": APP, "nethiro": APP, "trainhiro": APP, "studyhiro": APP, "codehiro": APP,
          "aicam": AICAM}
# Where each deploy is checked on Simone (127.0.0.1 there): the core's /status, each app's /api/health
CORE_HEALTH = "http://127.0.0.1:18080/status"
APP_PORT = {"homehiro": 8100, "nethiro": 8130, "trainhiro": 8140, "studyhiro": 8110, "codehiro": 8120}
SERVER = "simone"
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", SERVER]
# Log lines that count as an error after a deploy
ERROR_RE = re.compile(r"\b(ERROR|CRITICAL)\b|Traceback \(most recent call last\)")
# Camera addresses are redacted from anything shown (working rules, LAN only)
CAMERA_URL_RE = re.compile(r"\b(rtsps?|rtmp)://\S+")
# aicam: a changed top folder -> what to restart for it (compose.yaml's services; host/ and ha/ have their own steps)
AICAM_RESTART = {
    "netmon": "docker compose up -d netmon netprobe camwatch dhcplog",
    "dhcp": "docker compose up -d dhcp", "adguard": "docker compose up -d adguard",
    "caddy": "docker compose up -d caddy (or a Caddy reload)", "mosquitto": "docker compose up -d mosquitto",
    "piper": "docker compose up -d piper", "talker": "docker compose up -d talker",
    "frigate": "docker compose up -d frigate (then Frigate's two patches: CLAUDE.md rule 7)",
    "wakeword": "docker compose up -d wakeword", "toon": "docker compose up -d toon",
    "compose.yaml": "docker compose up -d <the services whose block changed>",
    "host": "sudo ~/aicam/host/install.sh, then ~/aicam/host/check.sh",
    "ha": "Home Assistant: Michel's call (CLAUDE.md rule 4)",
}


# ------------------------------------------------------------------------------------------------- the pure parts


@dataclass
class Facts:
    """What the PC, GitHub and Simone hold for one repo, read before anything moves."""
    repo: str
    head: str                                   # env0's dev/main
    github: str | None = None                   # origin's same branch (None: not there yet)
    live: str | None = None                     # what runs (None: no server for this repo, or nothing deployed yet)
    github_lacks: list[str] = field(default_factory=list)   # "sha subject" lines, newest first
    live_lacks: list[str] = field(default_factory=list)
    github_ahead: bool = False                  # GitHub has commits dev/main lacks
    live_ahead: bool = False                    # the server has commits dev/main lacks
    server_ahead: bool = False                  # aicam: Simone's bare repo has commits dev/main lacks
    live_dirty: int = 0                         # aicam: uncommitted files in ~/aicam
    error: str = ""                             # couldn't be read


def problems(f: Facts) -> list[str]:
    """Why a repo can't move. Any of these stops the whole train before anything moves: never forced."""
    out = []
    if f.error:
        out.append(f.error)
    if f.github_ahead:
        out.append("GitHub has commits this PC lacks: pull them into env0 first")
    if f.live_ahead or f.server_ahead:
        out.append("the server has commits this PC lacks: bring them to the PC first (they'd be lost otherwise)")
    if f.live_dirty:
        out.append(f"~/aicam has {f.live_dirty} uncommitted file(s) on Simone: commit them there first "
                   "(aicam's CLAUDE.md, rule 2)")
    return out


@dataclass
class Plan:
    push: list[str]                  # to GitHub, side by side
    first: list[str]                 # deployed alone, first (the core)
    then: list[str]                  # deployed side by side after it (apps, aicam)
    stops: dict[str, list[str]]      # repo -> why the train can't go

    @property
    def deploys(self) -> list[str]:
        return self.first + self.then

    @property
    def empty(self) -> bool:
        return not (self.push or self.deploys)


def choose(names: list[str]) -> list[str]:
    """The repos a train covers, in the standard's order (the core first): the ones named, or every repo."""
    if not names:
        return list(hw.REPOS)
    unknown = [n for n in names if n not in hw.REPOS]
    if unknown:
        raise hw.Stop(f"Unknown repo(s): {', '.join(unknown)}. Repos: {', '.join(hw.REPOS)}.")
    return [r for r in hw.REPOS if r in names]


def make_plan(facts: list[Facts]) -> Plan:
    """What moves: GitHub gets every repo it lacks commits of; the core deploys first when live lacks something,
    then the other deploys side by side."""
    stops = {f.repo: p for f in facts if (p := problems(f))}
    push = [f.repo for f in facts if f.github_lacks]
    live = [f.repo for f in facts if f.live_lacks and f.repo in DEPLOY]
    return Plan(push=push, first=[r for r in live if DEPLOY[r] == CORE],
                then=[r for r in live if DEPLOY[r] != CORE], stops=stops)


def deployed(repo: str, output: str) -> bool:
    """A hook's own last word: the core says "hiroleague: deployed <release>", an app "<app>: deployed". A post-receive
    hook can't fail the push, so its output is the only way to know."""
    if DEPLOY.get(repo) == CORE:
        return re.search(r"^(remote:\s*)?hiroleague: deployed \S", output, re.M) is not None
    return re.search(rf"^(remote:\s*)?{re.escape(repo)}: deployed\s*$", output, re.M) is not None


def redact(line: str) -> str:
    return CAMERA_URL_RE.sub(r"\1://<redacted>", line)


def error_lines(log: str, limit: int = 5) -> tuple[int, list[str]]:
    """The error lines in a log: how many, and the first few, camera addresses redacted."""
    hits = [redact(ln.strip()) for ln in log.splitlines() if ERROR_RE.search(ln)]
    return len(hits), hits[:limit]


def restart_hints(changed: list[str]) -> list[str]:
    """aicam: what may need a restart (or another step) for the files a pull brought, by their top folder."""
    tops = sorted({path.split("/", 1)[0] for path in changed if path})
    return [f"{top}: {AICAM_RESTART[top]}" for top in tops if top in AICAM_RESTART]


def iso(at: float) -> str:
    """Epoch seconds as hiro-work's events say a time."""
    return datetime.fromtimestamp(at).astimezone().isoformat(timespec="seconds")


def task_id(now: datetime) -> str:
    return "train-" + now.strftime("%Y%m%d-%H%M%S")


# --------------------------------------------------------------------------------------------------- output


class Out:
    """Every line on screen and in the train's log, whole lines even from threads."""

    def __init__(self, log: Path | None):
        self.log, self.lock = log, threading.Lock()
        if log:
            log.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, msg: str = "") -> None:
        with self.lock:
            print(msg, flush=True)
            if self.log:
                with open(self.log, "a", encoding="utf-8") as f:
                    f.write(msg + "\n")


@contextlib.contextmanager
def timed(out: Out, task: str, name: str, repo: str | None = None, log: Path | None = None):
    """One timed step, as hiro-work's own (start and end events), printed through the train's output. ``log``: its
    own log, whose last lines go with a failed end (CodeHiro's Work area shows them)."""
    label = name + (f" [{repo}]" if repo else "")
    out(f"> {label}")
    hw.event(task=task, env=0, repo=repo, step=name, phase="start", **({"log": str(log)} if log else {}))
    t = time.monotonic()
    try:
        yield
    except BaseException as e:
        s = round(time.monotonic() - t, 1)
        hw.event(task=task, env=0, repo=repo, step=name, phase="end", ok=False, seconds=s, error=str(e)[:300],
                 tail=hw.tail(log))
        out(f"x {label} failed after {s} s: {e}")
        raise
    s = round(time.monotonic() - t, 1)
    hw.event(task=task, env=0, repo=repo, step=name, phase="end", ok=True, seconds=s)
    out(f"  {label} done in {s} s")


# ------------------------------------------------------------------------------------------- reading the state


def bare_name(repo: str) -> str | None:
    """The server's bare repo for a repo (its `server` remote, simone:<name>.git), or None when it has none."""
    url = hw.git(hw.repo_dir(0, repo), "remote", "get-url", "server", check=False)
    m = re.match(rf"^{SERVER}:(?:~/)?([\w.-]+?)(?:\.git)?$", url.strip())
    return m.group(1) if m else None


def read_server(repos: list[str]) -> dict[str, str]:
    """One ssh call: each bare repo's main, and ~/aicam's commit and uncommitted files."""
    lines = []
    for repo in repos:
        name = bare_name(repo) if repo in DEPLOY else None
        if name:
            lines.append(f'echo "{repo} $(git --git-dir="$HOME/{name}.git" rev-parse -q --verify refs/heads/main '
                         '|| echo none)"')
    if "aicam" in repos:
        lines += ['echo "aicam-live $(git -C "$HOME/aicam" rev-parse HEAD)"',
                  'echo "aicam-dirty $(git -C "$HOME/aicam" status --porcelain | wc -l)"']
    if not lines:
        return {}
    out = subprocess.run([*SSH, "\n".join(lines)], capture_output=True, text=True, encoding="utf-8",
                         errors="replace", timeout=60)
    if out.returncode != 0:
        raise hw.Stop(f"Simone didn't answer over ssh: {(out.stderr or out.stdout).strip()[-500:]}")
    return dict(ln.split(" ", 1) for ln in out.stdout.splitlines() if " " in ln)


def has(d: Path, sha: str) -> bool:
    return subprocess.run(["git", "-C", str(d), "cat-file", "-e", f"{sha}^{{commit}}"],
                          capture_output=True).returncode == 0


def ancestor(d: Path, a: str, b: str) -> bool:
    return subprocess.run(["git", "-C", str(d), "merge-base", "--is-ancestor", a, b],
                          capture_output=True).returncode == 0


def lacks(d: Path, since: str | None, head: str) -> list[str]:
    rng = head if since is None else f"{since}..{head}"
    return [ln for ln in hw.git(d, "log", "--format=%h %s", rng).splitlines() if ln]


def read_facts(repo: str, server: dict[str, str]) -> Facts:
    """A repo's facts: GitHub fetched again (the standard: fetch before deploying), the server as read."""
    d, main = hw.repo_dir(0, repo), hw.main_of(repo)
    head = hw.git(d, "rev-parse", main)
    f = Facts(repo=repo, head=head)
    fetched = subprocess.run(["git", "-C", str(d), "fetch", "-q", "origin", main], capture_output=True, text=True)
    if fetched.returncode != 0:
        f.error = f"GitHub couldn't be read: {fetched.stderr.strip()[-200:]}"
        return f
    f.github = hw.git(d, "rev-parse", "-q", "--verify", f"refs/remotes/origin/{main}", check=False) or None
    f.github_ahead = bool(f.github) and not ancestor(d, f.github, head)
    if not f.github_ahead:
        f.github_lacks = lacks(d, f.github, head)
    if repo not in DEPLOY:
        return f
    bare = server.get(repo, "none").strip()
    if repo == "aicam":
        f.live = server.get("aicam-live", "").strip() or None
        f.live_dirty = int(server.get("aicam-dirty", "0").strip() or 0)
        f.server_ahead = bare != "none" and not (has(d, bare) and ancestor(d, bare, head))
    else:
        f.live = None if bare == "none" else bare
    if f.live and not (has(d, f.live) and ancestor(d, f.live, head)):
        f.live_ahead = True
    elif not f.live_ahead:
        f.live_lacks = lacks(d, f.live, head)
    return f


def gather(repos: list[str]) -> list[Facts]:
    server = read_server(repos)
    with ThreadPoolExecutor(max_workers=len(repos)) as pool:
        return list(pool.map(lambda r: read_facts(r, server), repos))


# --------------------------------------------------------------------------------------------- showing the plan


def show(out: Out, facts: list[Facts], plan: Plan) -> None:
    for f in facts:
        where = "GitHub only" if f.repo not in DEPLOY else ("live: " + (f.live[:8] if f.live else "nothing yet"))
        out(f"{f.repo}  ({hw.main_of(f.repo)} {f.head[:8]}; {where})")
        for why in plan.stops.get(f.repo, []):
            out(f"  x {why}")
        if f.github_lacks:
            out(f"  GitHub lacks {len(f.github_lacks)}:")
            out("\n".join(f"    {c}" for c in f.github_lacks[:15]))
        if f.live_lacks:
            out(f"  live lacks {len(f.live_lacks)}:")
            out("\n".join(f"    {c}" for c in f.live_lacks[:15]))
        if len(f.live_lacks) > 15 or len(f.github_lacks) > 15:
            out("    ...")
        if not (f.github_lacks or f.live_lacks or plan.stops.get(f.repo)):
            out("  up to date")
    out("")
    out("Plan:")
    out("  1. push to GitHub, side by side: " + (", ".join(plan.push) or "nothing"))
    out("  2. deploy first: " + (", ".join(plan.first) or "(the core has nothing new)"))
    out("  3. then deploy side by side: " + (", ".join(plan.then) or "nothing"))
    out("  4. verify each deploy, then one report")
    left = [r for r in hw.KIT_READERS if r not in plan.deploys]
    kit = core_kit_changes(facts) if left else 0
    if kit:
        out(f"  note: the core's kits changed ({kit} file(s)); {', '.join(left)} get them at their next deploy, "
            "or now with `ssh simone 'cd ~/<app> && ./deploy.sh'`")


def core_kit_changes(facts: list[Facts]) -> int:
    core = next((f for f in facts if f.repo == "hiroleague" and f.live_lacks), None)
    if not core:
        return 0
    rng = core.head if core.live is None else f"{core.live}..{core.head}"
    return len(hw.git(hw.repo_dir(0, "hiroleague"), "diff", "--name-only", rng, "--", *hw.KIT_PATHS).splitlines())


# ---------------------------------------------------------------------------------------------- moving things


@dataclass
class Result:
    repo: str
    pushed: int = 0
    deployed: bool | None = None     # None: not deployed by this train
    answers: bool | None = None
    errors: int = 0
    error_samples: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    failed: str = ""


def stream(out: Out, args: list[str], cwd: Path | None, repo: str, log: Path,
           on_line: Callable[[str], None] | None = None) -> tuple[int, str]:
    """A command's output, live with the repo's name before each line, and kept in its own log. ``on_line`` reads
    each line as it comes (a deploy's stages)."""
    log.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace")
    lines = []
    with open(log, "w", encoding="utf-8") as f:
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            lines.append(line)
            f.write(line + "\n")
            out(f"  {repo:10} | {redact(line)}")
            if on_line:
                on_line(line)
    return proc.wait(), "\n".join(lines)


def push_github(out: Out, task: str, f: Facts, r: Result) -> None:
    main = hw.main_of(f.repo)
    log = hw.LOGS / "train" / f"{task}-{f.repo}-github.log"
    with timed(out, task, "push github", f.repo, log):
        code, text = stream(out, ["git", "-C", str(hw.repo_dir(0, f.repo)), "push", "origin", f"{main}:{main}"],
                            None, f.repo, log)
        if code != 0:
            raise hw.Stop(f"git refused the push to GitHub (never forced): {text[-300:]}")
    r.pushed = len(f.github_lacks)
    hw.record_commits(task, 0, f.repo, f.github, f.head, "push")


def deploy(out: Out, task: str, f: Facts, r: Result) -> None:
    """The repo's own deploy (its hook on Simone), then the checks that it went live."""
    d, main = hw.repo_dir(0, f.repo), hw.main_of(f.repo)
    since = int(time.time()) - 5  # Simone's log lines from here on are this deploy's (clocks within seconds)
    log = hw.LOGS / "train" / f"{task}-{f.repo}-deploy.log"
    # Its stages (the checks, the build and the tests in it, the migrations' trial, the start), timed inside "deploy"
    # as the deploy's own lines name them
    stages = Stages(f.repo, lambda at, **e: hw.event(task=task, env=0, repo=f.repo, parent="deploy", at=iso(at), **e))
    try:
        with timed(out, task, "deploy", f.repo, log):
            went = False
            try:
                code, text = stream(out, ["git", "-C", str(d), "push", "server", f"{main}:main"], None, f.repo, log,
                                    stages.line)
                went = code == 0 and (DEPLOY[f.repo] == AICAM or deployed(f.repo, text))
            finally:
                stages.close(went)
            if code != 0:
                raise hw.Stop(f"git refused the push to Simone (never forced): {text[-300:]}")
            if DEPLOY[f.repo] == AICAM:
                code, text = stream(out, [*SSH, "git -C ~/aicam pull --ff-only"], None, f.repo, log)
                if code != 0:
                    raise hw.Stop(f"~/aicam's pull failed: {text[-300:]}")
                changed = hw.git(d, "diff", "--name-only", f"{f.live}..{f.head}").splitlines() if f.live else []
                r.notes += [f"may need: {h}" for h in restart_hints(changed)]
            elif not deployed(f.repo, text):
                raise hw.Stop(f"its deploy didn't finish (log: {log}); its own way back ran if it got that far")
        r.deployed = True
        hw.record_commits(task, 0, f.repo, f.live, f.head, "deploy")  # what went live: CodeHiro names its tasks
    except hw.Stop as e:
        r.deployed, r.failed = False, str(e)
    with contextlib.suppress(hw.Stop):
        verify(out, task, f, r, since)


def verify(out: Out, task: str, f: Facts, r: Result, since: int) -> None:
    """The standard's "Verify after a deploy": it answers, and its log shows no new errors."""
    kind = DEPLOY[f.repo]
    if kind == AICAM:
        script = 'git -C ~/aicam rev-parse HEAD; git -C ~/aicam status --porcelain | wc -l'
    elif kind == CORE:
        script = (f"curl -fsS --max-time 5 {CORE_HEALTH} | grep -q '\"running\": *true' && echo ANSWERS || echo SILENT;"
                  f" journalctl -u hiro --since @{since} --no-pager -o cat 2>/dev/null | tail -n 2000")
    else:
        script = (f"curl -fsS --max-time 5 http://127.0.0.1:{APP_PORT[f.repo]}/api/health >/dev/null && echo ANSWERS "
                  f"|| echo SILENT; docker logs --since {since} {f.repo} 2>&1 | tail -n 2000")
    with timed(out, task, "verify", f.repo):
        res = subprocess.run([*SSH, script], capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=120)
        lines = res.stdout.splitlines()
        if kind == AICAM:
            r.answers = bool(lines) and lines[0].strip() == f.head and lines[-1].strip() == "0"
            if not r.answers:
                raise hw.Stop("~/aicam isn't at the pushed commit, or has uncommitted files")
            return
        r.answers = bool(lines) and lines[0].strip() == "ANSWERS"
        r.errors, r.error_samples = error_lines("\n".join(lines[1:]))
        if not r.answers:
            raise hw.Stop("it doesn't answer")
        if r.errors:
            raise hw.Stop(f"{r.errors} error line(s) in its log since the deploy started")


def run_train(out: Out, task: str, facts: list[Facts], plan: Plan) -> list[Result]:
    by = {f.repo: f for f in facts}
    results = {f.repo: Result(f.repo) for f in facts if f.repo in plan.push or f.repo in plan.deploys}

    def push_one(repo: str) -> None:
        try:
            push_github(out, task, by[repo], results[repo])
        except hw.Stop as e:
            results[repo].failed = str(e)

    with timed(out, task, "push github"):
        with ThreadPoolExecutor(max_workers=max(1, len(plan.push))) as pool:
            list(pool.map(push_one, plan.push))
        failed = [r for r in plan.push if results[r].failed]
        if failed:
            raise hw.Stop("GitHub refused " + ", ".join(failed) + ": nothing is deployed (GitHub is never behind live)")
    for repo in plan.first:
        deploy(out, task, by[repo], results[repo])
        if not results[repo].deployed:
            out(f"x {repo} didn't deploy: the apps stay as they are")
            return list(results.values())
    if plan.then:
        with ThreadPoolExecutor(max_workers=len(plan.then)) as pool:
            list(pool.map(lambda repo: deploy(out, task, by[repo], results[repo]), plan.then))
    return list(results.values())


def report(out: Out, task: str, results: list[Result], started: float) -> bool:
    out("")
    out(f"Deploy train {task}: {round(time.monotonic() - started)} s")
    ok = True
    for r in results:
        parts = []
        if r.pushed:
            parts.append(f"GitHub +{r.pushed}")
        if r.deployed is not None:
            parts.append("deployed" if r.deployed else "NOT deployed")
        if r.answers is not None:
            parts.append("answers" if r.answers else "DOESN'T ANSWER")
        if r.errors:
            parts.append(f"{r.errors} new error line(s)")
        out(f"  {r.repo:11} " + ", ".join(parts or ["nothing done"]))
        if r.failed:
            out(f"    x {r.failed}")
        out("\n".join(f"    | {s}" for s in r.error_samples))
        out("\n".join(f"    {n}" for n in r.notes))
        ok = ok and not r.failed and r.deployed is not False and r.answers is not False and not r.errors
    out("All went live and answer." if ok else "Not everything went live cleanly: read the lines above.")
    out(f"Logs: {hw.LOGS / 'train'}")
    return ok


# ---------------------------------------------------------------------------------------------- the command


def open_window(a) -> None:
    """The train runs in a window Michel watches (and answers the question in), outside Claude."""
    task = task_id(datetime.now())
    args = [sys.executable, str(Path(hw.__file__).resolve()), "train", "--here", "--id", task, *a.repos]
    if a.yes:
        args.append("--yes")
    wt = [shutil.which("wt.exe") or "wt.exe", "-w", "hiro-train", "new-tab", "--title", "deploy train",
          "cmd", "/k", *args]
    subprocess.Popen(wt, creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    hw.say(f"The deploy train {task} runs in the 'hiro-train' window. Its log: {hw.LOGS / 'train' / (task + '.log')}")


@contextlib.contextmanager
def one_train():
    lock = hw.RUN / "train.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise hw.Stop(f"Another deploy train is running ({lock}; delete it if none is).") from None
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def cmd_train(a) -> None:
    repos = choose(a.repos)
    if not (a.dry_run or a.here):
        open_window(a)
        return
    task = a.id or task_id(datetime.now())
    out = Out(None if a.dry_run else hw.LOGS / "train" / f"{task}.log")
    started = time.monotonic()
    if a.dry_run:
        out(f"Deploy train (dry run: nothing moves): {', '.join(repos)}")
        facts = gather(repos)
        plan = make_plan(facts)
        out("")
        show(out, facts, plan)
        if plan.stops:
            out("\nThe train would stop here: " + "; ".join(plan.stops))
        return
    with one_train():
        hw.event(task=task, env=0, step="task", phase="start", kind="deploy", repos=repos, title="Deploy train")
        ok = False
        try:
            out(f"Deploy train {task}: {', '.join(repos)}")
            with timed(out, task, "plan"):
                facts = gather(repos)
                plan = make_plan(facts)
            out("")
            show(out, facts, plan)
            if plan.stops:
                raise hw.Stop("nothing moved: " + "; ".join(f"{r}: {', '.join(w)}" for r, w in plan.stops.items()))
            if plan.empty:
                out("\nNothing to ship: GitHub and live have everything.")
                ok = True
                return
            if not a.yes:
                if not sys.stdin.isatty():
                    raise hw.Stop("no one to ask: run it in a terminal, or with --yes")
                try:
                    answer = input("\nGo? [y/N] ")
                except EOFError:  # Windows' NUL passes for a terminal: no answer is a no
                    answer = ""
                if answer.strip().lower() not in ("y", "yes"):
                    raise hw.Stop("not started: nothing moved")
                # The train's time runs from the go: the minutes it waited for Michel's answer aren't the train's
                started = time.monotonic()
            out("")
            results = run_train(out, task, facts, plan)
            ok = report(out, task, results, started)
        except hw.Stop as e:
            out(f"\nStopped: {e}")
            raise
        finally:
            hw.event(task=task, env=0, step="task", phase="end", ok=ok,
                     seconds=round(time.monotonic() - started, 1))
        if not ok:
            raise hw.Stop("the train finished with failures (above)")


def add_parser(sub) -> None:
    t = sub.add_parser("train", help="the deploy train: push and deploy what GitHub and live lack (when Michel says)")
    t.add_argument("repos", nargs="*", help="only these repos (none: every repo)")
    t.add_argument("--dry-run", action="store_true", help="show what lacks what and the plan; nothing moves")
    t.add_argument("--yes", action="store_true", help="don't ask before it moves")
    t.add_argument("--here", action="store_true", help="run in this terminal (else it opens the hiro-train window)")
    t.add_argument("--id", help=argparse.SUPPRESS)  # the window's run: the task the opening call named
