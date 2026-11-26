r"""hiro-work: the environments every Hiro League task works in (hiro-docs standards/workflow.md).

env0 (C:\hiro\env0) is main: the main checkouts on dev/main, what the next deploy ships, and Michel's dev
servers on it. No task works there. Every task reserves the repos it changes and works in one of env1..env5: the same
repos as git worktrees, kept warm between tasks, each with its own data (C:\hiro\data\envN) and its own block of ports
(7N00-7N49), its reserved repos on the branch task/<task>. A task merges when it should ship: its branches merge into
dev/main and env0 is brought up to them. Until then its commits stay on its branch.

A plan that ships whole (hiro-work plan send, "ships": "whole") has a branch of its own, plan/<name>, in each repo it
changes: its phases branch from it and merge back into it, and it reaches dev/main only when it lands. A task's
target says where its work goes: dev/main, or its plan's branch. A plan's branch is never checked out.

    hiro-work status                         environments, tasks, reserved repos, servers
    hiro-work start <task> --repos a,b [--kit] [--title ...] [--about ...] [--part-of ... [--phase ...]]
                    [--own-branch] [--on-main] [--env N]
    hiro-work describe <task> [--about ...] [--part-of ...]   what it does / what it is part of, changed
    hiro-work sync <task>                    bring the latest dev/main into the task's branch, without merging the task
    hiro-work merge <task>                   bring the latest in, check, update env0, release the environment
    hiro-work pause <task> / resume <task>   save the work on its branch and release the environment / take one back
    hiro-work up <env> [server ...] / down <env> [server ...]   servers, in Windows Terminal outside Claude
    hiro-work init <env>                     make (or repair) an environment: worktrees, installs, settings
    hiro-work sweep                          what is left behind (report only)
    hiro-work review <task>                  the task waits for Michel's review (until its next step)
    hiro-work switch <env> [--preset NAME] [--set ai=real]   env1..5: what it reaches of each system (switches.py)
    hiro-work preset list | save <name> --from <env> | remove <name>   the switchboard's presets
    hiro-work refresh-data [--apply STAMP] [--files]   live -> env0: a scrubbed live copy, then env0 (data.py)
    hiro-work data <env> <source>            env1..5: its data from env0, vanilla or a live copy (data.py)
    hiro-work secret list | fill | set <name>  the PC's dev secrets, by name; set asks for the value (data.py)
    hiro-work copy-list [--check]   every repo's copy list (data.toml): what a copy holds, and how (data.py)
    hiro-work deploy [repo ...] [--dry-run]  the deploy: push and deploy, when Michel says (deploy.py)
    hiro-work audit latest | RUN | list      the doc audit's runs, and start / report to record one (audit.py)
    hiro-work docs open | publish -m "..." | undo   the docs desk: the standard's documents, with no task (docs.py)

State lives in C:\hiro\tasks (one JSON file per task) and every step is logged to C:\hiro\logs\events.jsonl (with
its time) for CodeHiro's Work area, where ship.py sends it. Standard library only: it runs on the system Python.
"""

from __future__ import annotations

import argparse
import contextlib
import contextvars
import hashlib
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import apps as appfile
import data
import ship
import switches

ROOT = Path(os.environ.get("HIRO_ROOT", r"C:\hiro"))
TASKS = ROOT / "tasks"
LOGS = ROOT / "logs"
EVENTS = LOGS / "events.jsonl"
ENVS = range(0, 6)

# The repos every environment holds, the core first (it merges first), the apps as apps.toml lists them.
# hiroleague-website lives in env0 only.
REPOS = ["hiroleague", *(a.repo for a in appfile.APPS), "aicam", "hiro-docs"]
MAIN = {"hiroleague": "dev", "hiro-docs": "dev"}  # every other repo's main branch is main
# The apps that read the core's kits, SDK and build kit (../hiroleague): a change there reserves them too.
KIT_READERS = [a.repo for a in appfile.APPS]
KIT_PATHS = ["hiroserver/hiro-extension-kit", "hiroserver/hiro-channel-sdk", "hiroserver/hiro-commons",
             "ui-kit", "build-kit"]
# What each repo installs, and the lock file that says when to install again
PYTHON = {"hiroleague": ["hiroserver"], **{a.repo: [a.backend] for a in appfile.APPS}}
NODE = {"hiroleague": ["admin_frontend", "ui-kit"], **{a.repo: [a.frontend] for a in appfile.APPS}}
# The apps whose data an environment copies from env0 (C:\hiro\data\envN\<repo>; the core's is "core")
APPS = [a.repo for a in appfile.APPS if a.copy_data]
# The apps `up` runs: every app
SERVED = [a.repo for a in appfile.APPS]
# The core's other listeners come with its server: their port names start it too (`up 0 core-admin` = `up 0 core`)
PORT_ALIASES = {"core-admin": "core", "core-socket": "core", "core-http": "core", "core-gateway": "core"}
_lists: data.Lists | None = None


def copy_lists() -> data.Lists:
    """Every repo's copy list (data.toml), read once from env0's repos, main's (copylist.py)."""
    global _lists
    if _lists is None:
        try:
            _lists = data.load(env_dir(0))
        except data.copylist.ListError as exc:
            raise Stop(f"A copy list is wrong: {exc}") from exc
    return _lists


def main_of(repo: str) -> str:
    return MAIN.get(repo, "main")


def env_dir(env: int) -> Path:
    return ROOT / f"env{env}"


def repo_dir(env: int, repo: str) -> Path:
    return env_dir(env) / repo


def data_dir(env: int) -> Path:
    return ROOT / "data" / f"env{env}"


def ports(env: int) -> dict[str, int]:
    """The environment's block, 7N00-7N49 (workflow.md, Ports; apps.py). The core listens on its admin API, the
    extension socket (the channel plugins and the apps), its HTTP status API and its gateway."""
    return appfile.ports(env)


def app_data(env: int, a: appfile.App) -> Path:
    """Where an app keeps its data in an environment: env0's own folder or its repo's data/ (apps.toml), envN's."""
    return repo_dir(0, a.repo) / "data" if env == 0 and a.data == "repo" else data_dir(env) / a.repo


def workspace_name(env: int) -> str:
    """The core's workspace for an environment, in the machine's one workspace registry."""
    return "default" if env == 0 else f"env{env}"


# ---------------------------------------------------------------------------------------------------------- output


def say(msg: str) -> None:
    print(msg, flush=True)


def utf8_output() -> None:
    """stdout and stderr write UTF-8, a character they can't write as "?" (once, at the start).

    Piped (a session's Bash), Python's stdout on Windows is cp1252: a commit subject with "→" made
    ``deploy --dry-run`` crash (UnicodeEncodeError). A console prints Unicode, so only a piped run broke."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


_shipping = False  # this process has started the sender (ship.py) once
_event_lock = threading.Lock()


def event(**fields) -> None:
    global _shipping
    LOGS.mkdir(parents=True, exist_ok=True)
    fields = {"at": datetime.now().astimezone().isoformat(timespec="seconds"), **fields}
    # Through the log's lock: a merge's checks run side by side, and their engines write beside this process. This
    # process's threads take turns first: on Windows a locked file is tried again only after a whole second
    with _event_lock:
        ship.append(EVENTS, fields)
        # The log is the outbox: the sender posts the new lines to CodeHiro. Only the real log is sent (a test's
        # isn't).
        if not _shipping and EVENTS == ship.EVENTS:
            _shipping = True
            ship.kick()


TAIL_LINES = 100  # a failed step's last lines of log, sent with its end (CodeHiro can't read the PC's files)
TAIL_CHARS = 20_000
# The steps open around the code running now, the innermost last: a new one runs inside it. A context variable, so
# a merge's checks running side by side in threads (each started in a copy of the merge's context) each have their own
_open_steps: contextvars.ContextVar[tuple[str, ...]] = contextvars.ContextVar("open_steps", default=())


def tail(log: Path | None) -> str | None:
    if not log or not log.exists():
        return None
    with contextlib.suppress(OSError):
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()[-TAIL_LINES:]
        return "\n".join(lines)[-TAIL_CHARS:]
    return None


class Outcome:
    """What a step yields: ``fail()`` marks it failed without stopping the command (a repo's check that failed while
    the others go on)."""

    def __init__(self) -> None:
        self.error: str | None = None

    def fail(self, error: str) -> None:
        self.error = error


def side_by_side() -> bool:
    """Steps run side by side in threads (a merge's checks); the main thread's run one at a time."""
    return threading.current_thread() is not threading.main_thread()


@contextlib.contextmanager
def step(task: str | None, env: int | None, name: str, repo: str | None = None, log: Path | None = None,
         **more):
    """One timed step: printed, and logged as a start and an end event. A step inside another names it as its
    ``parent`` (merge's own steps); ``log`` is its log file, whose last lines go with a failed end; ``more`` rides on
    both events (the servers of servers up)."""
    label = f"{name}" + (f" [{repo}]" if repo else "")
    say(f"> {label}")
    where = {"task": task, "env": env, "repo": repo, "step": name}
    if opened := _open_steps.get():
        where["parent"] = opened[-1]
    event(**where, phase="start", **({"log": str(log)} if log else {}), **more)
    token = _open_steps.set((*opened, name))
    t = time.monotonic()
    outcome = Outcome()
    try:
        yield outcome
    except BaseException as e:
        s = round(time.monotonic() - t, 1)
        event(**where, phase="end", ok=False, seconds=s, error=str(e)[:300], tail=tail(log), **more)
        say(f"x {label} failed after {s} s")
        raise
    finally:
        _open_steps.reset(token)
    s = round(time.monotonic() - t, 1)
    if outcome.error:
        event(**where, phase="end", ok=False, seconds=s, error=outcome.error[:300], tail=tail(log), **more)
        say(f"x {label} failed after {s} s")
        return
    event(**where, phase="end", ok=True, seconds=s, **more)
    # The step's name when steps run side by side (a merge's checks), so each "done" says whose it is
    say(f"  done in {s} s" + (f" ({label})" if side_by_side() else ""))


COMMITS_MAX = 2000  # one event's commits, at most


def record_commits(task: str, env: int | None, repo: str, frm: str | None, to: str | None, how: str) -> None:
    """The commits a task (or a deploy) added to a repo, from..to in env0, as a Work event: CodeHiro's Deploys
    shows the tasks whose work each deploy shipped. ``how``: merge, deploy, push."""
    if not frm or not to or frm == to:
        return
    shas = git(repo_dir(0, repo), "rev-list", f"{frm}..{to}", check=False).split()[:COMMITS_MAX]
    if shas:
        event(task=task, env=env, repo=repo, step="commits", phase="end", ok=True, how=how,
              **{"from": frm, "to": to}, commits=shas)


class Stop(Exception):
    """A refusal with a message for the person: nothing half-done is left behind."""


# ------------------------------------------------------------------------------------------------------- commands


# Why: the PC's helper (relay.py) runs as pythonw, with no console; each git it starts would open a console window of
# its own, flashing on screen every minute. The output is captured, so no command here needs a window.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run(args: list[str], cwd: Path | None = None, check: bool = True) -> str:
    out = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                         creationflags=NO_WINDOW)
    if check and out.returncode != 0:
        raise Stop(f"{' '.join(args[:4])} failed in {cwd}:\n{(out.stderr or out.stdout).strip()[-1500:]}")
    return out.stdout.strip()


def git(repo_path: Path, *args: str, check: bool = True) -> str:
    return run(["git", "-C", str(repo_path), *args], check=check)


def dirty(repo_path: Path) -> list[str]:
    """Uncommitted work: changed, staged or untracked files (.gitignore respected)."""
    return [line for line in git(repo_path, "status", "--porcelain").splitlines() if line.strip()]


def changed_repos(env: int, tasks: list[Task]) -> list[str]:
    """The repos an environment has changed, for CodeHiro's environment card (relay.py posts it; the card dims a reserved
    repo that isn't here). A repo its task reserves: uncommitted files, or commits since the task's base. Any other repo:
    uncommitted files."""
    task = next((t for t in tasks if t.env == env and t.state == "working"), None)
    out = []
    for repo in REPOS:
        d = repo_dir(env, repo)
        if not (d / ".git").exists():
            continue
        files = dirty(d)
        if task and repo in task.repos:
            base = task.base.get(repo)
            if files or (base and git(d, "rev-parse", "HEAD") != base):
                out.append(repo)
        elif files:
            out.append(repo)
    return out


def leftovers(env: int, tasks: list[Task]) -> list[dict[str, str]]:
    """What an environment holds that no task there owns, for the foot of CodeHiro's environment card (relay.py posts
    it): a repo its task doesn't reserve with uncommitted files, and in env1..env5 with no task, any repo that isn't as a
    free environment's should be: on a branch of its own (not detached), or with commits main lacks. Being behind
    main isn't one: a free environment stays where its last task left it, and the next start brings it up.
    One row per repo: ``{"repo", "what"}``, what is wrong in words."""
    task = next((t for t in tasks if t.env == env and t.state == "working"), None)
    out = []
    for repo in REPOS:
        d = repo_dir(env, repo)
        if not (d / ".git").exists() or (task and repo in task.repos):
            continue
        n = len(dirty(d))
        what = [f"{n} uncommitted file{'' if n == 1 else 's'}"] if n else []
        if env and not task:
            main = main_of(repo)
            branch = git(d, "branch", "--show-current")
            if branch:
                what.append(f"on branch {branch}")
            ahead = int(git(d, "rev-list", "--count", f"{main}..HEAD"))
            if ahead:
                what.append(f"{ahead} commit{'' if ahead == 1 else 's'} not on {main}")
        if what:
            out.append({"repo": repo, "what": ", ".join(what)})
    return out


# ---------------------------------------------------------------------------------------------------------- state


@dataclass
class Task:
    id: str
    title: str
    env: int | None
    repos: list[str]
    state: str = "working"  # working | paused | done (merged) | cancelled (ended unmerged: hiro-work reopen)
    base: dict[str, str] = field(default_factory=dict)
    # In env1..env5: its switchboard (switches.py): a preset, and the systems changed from it ({"ai": "real"})
    preset: str = switches.DEFAULT
    switches: dict[str, str] = field(default_factory=dict)
    # Its sign-in there, for interactive use: "on" (as live), "off" (everyone is the owner) or "as" one person of the
    # family list (`sign_in_as`: their id or name, as asked; found in the environment's own list when the file is
    # written)
    sign_in: str = "on"
    sign_in_as: str = ""
    # What bigger work it is a piece of ("Work-flow plan"): CodeHiro names it "<part_of> › <title>" and groups by it
    part_of: str = ""
    # What it does, in a sentence: the Work area shows it under its name
    about: str = ""
    # Where its environment's data comes from (data.SOURCES): env0's copy, vanilla, live or live:<stamp>
    data: str = "env0"
    # Where its work goes when it merges: "" for dev/main, or its plan's branch (plan/<name>) when its plan ships
    # whole; `plan` is that plan's name. A record from before plans had branches has neither: it targets main.
    target: str = ""
    plan: str = ""
    # A landing task (hiro-work plan land): the plan's branch it brings onto main, the commit it took in each repo (a
    # phase merged into the branch meanwhile lands next time), and the phases that were In the plan when it started
    lands: str = ""
    landed: dict[str, str] = field(default_factory=dict)
    lands_phases: list[str] = field(default_factory=list)
    # Once merged: where its merge left each repo it brought commits to (dev/main, or its plan's branch). The deploy
    # moves its plan phase to Live once each runs live (plan.went_live). None: merged before hiro-work kept it
    merged_at: dict[str, str] | None = None
    created: str = ""
    updated: str = ""

    @property
    def branch(self) -> str:
        return f"task/{self.id}"


# A task that ended: merged (done), or cancelled. Its record moves to tasks/done; only a cancelled one can be reopened.
ENDED = ("done", "cancelled")


def cancelled_branch(task_id: str) -> str:
    """Where a cancelled task's work is kept, in each repo that has commits of its own (hiro-work reopen takes it back)."""
    return f"cancelled/{task_id}"


def task_path(task_id: str) -> Path:
    return TASKS / f"{task_id}.json"


def task_from(data: dict) -> Task:
    """A task record as this hiro-work knows it. Environments can run different versions of hiro-work, all sharing
    C:\\hiro\\tasks: a field a newer one wrote is left out here (it stays in the file, see record())."""
    return Task(**{k: v for k, v in data.items() if k in Task.__dataclass_fields__})


def record(task: Task) -> dict:
    """The task as JSON, keeping the fields a newer hiro-work wrote that this one doesn't know."""
    old: dict = {}
    with contextlib.suppress(OSError, ValueError):
        old = json.loads(task_path(task.id).read_text(encoding="utf-8"))
    return {**old, **task.__dict__}


def load_tasks() -> list[Task]:
    TASKS.mkdir(parents=True, exist_ok=True)
    return [task_from(json.loads(p.read_text(encoding="utf-8"))) for p in sorted(TASKS.glob("*.json"))]


def save(task: Task) -> None:
    task.updated = datetime.now().astimezone().isoformat(timespec="seconds")
    data = record(task)
    if task.state in ENDED:
        (TASKS / "done").mkdir(parents=True, exist_ok=True)
        task_path(task.id).unlink(missing_ok=True)
        (TASKS / "done" / f"{task.id}.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    else:
        task_path(task.id).write_text(json.dumps(data, indent=2), encoding="utf-8")


def get(task_id: str) -> Task:
    p = task_path(task_id)
    if not p.exists():
        raise Stop(f"No open task '{task_id}' (hiro-work status lists them).")
    return task_from(json.loads(p.read_text(encoding="utf-8")))


@contextlib.contextmanager
def locked():
    """One hiro-work at a time changes the state (several sessions may call it at once)."""
    TASKS.mkdir(parents=True, exist_ok=True)
    lock = TASKS / ".lock"
    deadline = time.monotonic() + 120
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            if time.time() - lock.stat().st_mtime > 1800:  # left by a crash
                lock.unlink(missing_ok=True)
                continue
            if time.monotonic() > deadline:
                raise Stop(f"Another hiro-work is still running ({lock}).")
            time.sleep(1)
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def expand(repos: list[str], kit: bool) -> list[str]:
    """The reserved repos, the core first; a kit change also reserves every app that reads the kits."""
    unknown = [r for r in repos if r not in REPOS]
    if unknown:
        raise Stop(f"Unknown repo(s): {', '.join(unknown)}. Repos: {', '.join(REPOS)}.")
    reserved = set(repos) | (set(KIT_READERS) | {"hiroleague"} if kit else set())
    return [r for r in REPOS if r in reserved]


def reserved_in(env: int, tasks: list[Task]) -> dict[str, str]:
    """repo -> the task holding it, in one environment."""
    return {r: t.id for t in tasks if t.state == "working" and t.env == env for r in t.repos}


def pick_env(tasks: list[Task], wanted: int | None) -> int:
    """The first free env1..env5, or the one asked for. env0 is main: no task works there (workflow.md)."""
    busy = {t.env for t in tasks if t.state == "working" and t.env is not None}
    if wanted == 0:
        raise Stop("env0 is main: no task works there. Leave out --env, or name a free env1 to env5.")
    if wanted is not None:
        if wanted in busy:
            raise Stop(f"env{wanted} is busy.")
        return wanted
    for env in ENVS:
        if env and env not in busy:
            return env
    raise Stop("Every environment is busy: merge or pause a task first (hiro-work status).")


def same_work(part_of: str, tasks: list[Task]) -> list[Task]:
    """The open tasks a new task with this --part-of belongs with: the task it names, or tasks part of the same work.
    A step of a task or plan joins it, on its branch, instead of starting one of its own (workflow.md, "Steps in other
    sessions")."""
    value = part_of.strip()
    if not value:
        return []
    name = part_of_name(value)
    return [t for t in tasks if t.state in ("working", "paused") and (value == t.id or name in (t.title, t.part_of))]


# ------------------------------------------------------------------------------------------------- environments


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.exists() else "none"


def needs_install(stamp: Path, lock: Path, force: bool) -> bool:
    """True when the lock file changed since the last install here. An install made before hiro-work (no stamp
    yet, env0's) is taken as matching: reinstalling it would only fight its running servers."""
    if force:
        return True
    if not stamp.exists():
        if stamp.parent.is_dir():
            stamp.write_text(file_sha(lock))
            return False
        return True
    return stamp.read_text() != file_sha(lock)


def ui_server_up(env: int, repo: str, sub: str) -> str | None:
    """The name of the environment's running dev server that holds this frontend's node_modules, or None. A running
    Vite loads native .node files (lightningcss) from it, and on Windows npm ci can't unlink them (EPERM)."""
    # The core's admin is the core's one served frontend (ui-kit has no server of its own); an app has one frontend
    name, served = ("core-ui", "admin_frontend") if repo == "hiroleague" else (f"{repo}-ui", sub)
    every = servers(env)
    return name if sub == served and name in every and listening(every[name].port) else None


def install(env: int, repo: str, task: str | None = None, force: bool = False, spare_servers: bool = False) -> list[str]:
    """Install a repo's packages in an environment only when its lock file changed since the last install there.
    spare_servers: a frontend whose dev server is up is left alone (its install waits); the servers' names come back."""
    held: list[str] = []
    for sub in PYTHON.get(repo, []):
        d = repo_dir(env, repo) / sub
        stamp, lock = d / ".venv" / ".hiro-lock", d / "uv.lock"
        if needs_install(stamp, lock, force):
            with step(task, env, "python install", f"{repo}/{sub}"):
                run(["uv", "sync"], cwd=d)
                stamp.write_text(file_sha(lock))
    for sub in NODE.get(repo, []):
        d = repo_dir(env, repo) / sub
        stamp, lock = d / "node_modules" / ".hiro-lock", d / "package-lock.json"
        if needs_install(stamp, lock, force):
            up = ui_server_up(env, repo, sub) if spare_servers else None
            if up:  # the stamp stays old, so the install runs the next time it is asked for with the server down
                held.append(up)
                continue
            with step(task, env, "node install", f"{repo}/{sub}"):
                run(["npm.cmd", "ci", "--prefer-offline", "--no-audit", "--no-fund"], cwd=d)
                stamp.write_text(file_sha(lock))
    return held


def memory_link(env: int, repo: str) -> None:
    """Sessions opened in envN share env0's Claude Code memory for that repo (memory is keyed by folder path)."""
    projects = Path.home() / ".claude" / "projects"
    src = projects / f"C--hiro-env0-{repo}" / "memory"
    dst_dir = projects / f"C--hiro-env{env}-{repo}"
    if not src.exists() or (dst_dir / "memory").exists():
        return
    dst_dir.mkdir(parents=True, exist_ok=True)
    run(["cmd", "/c", "mklink", "/J", str(dst_dir / "memory"), str(src)])


def init_env(env: int, task: str | None = None) -> None:
    """Make (or repair) envN: a detached worktree of each repo at env0's dev/main, its installs, its settings."""
    if env == 0:
        raise Stop("env0 is Michel's dev: its checkouts already exist.")
    env_dir(env).mkdir(parents=True, exist_ok=True)
    for repo in REPOS:
        src, dst = repo_dir(0, repo), repo_dir(env, repo)
        if not (dst / ".git").exists():
            with step(task, env, "worktree", repo):
                git(src, "worktree", "add", "--detach", str(dst), main_of(repo))
        # Untracked settings a worktree doesn't get: Claude's local permissions
        local = src / ".claude" / "settings.local.json"
        if local.exists() and not (dst / ".claude" / "settings.local.json").exists():
            (dst / ".claude").mkdir(exist_ok=True)
            shutil.copy2(local, dst / ".claude" / "settings.local.json")
        memory_link(env, repo)
    install_all(env, REPOS, task)
    # The git hooks (pre-commit check, post-checkout warning): every repo's core.hooksPath points at env0's core.
    # Worktrees share their repo's config, so this only matters for a repo env0 didn't have before.
    with step(task, env, "git hooks"):
        run([sys.executable, str(repo_dir(0, "hiroleague") / "build-kit" / "git-hooks" / "install.py")])


def install_all(env: int, repos: list[str], task: str | None = None) -> None:
    """Every repo's installs, one at a time: measured, side by side is no faster (npm ci is disk-bound: 13-17 s
    each alone, 58-104 s each when seven run at once), and one at a time keeps the output readable."""
    for repo in repos:
        install(env, repo, task)


# Sign-in follows the environment's switchboard: an AUTH line of env0's is dropped (sign-in on, so users and roles
# can be tried), and AUTH=off is written only where the task asked for sign-in off (sign_in_env). Sends and HA's
# automatic writes follow the switchboard too (switches.app_env), which every server reads (HIRO_SWITCHBOARD)
ENV_DEV_FORCED = {"AUTH": None}


def people_of(env: int) -> list[dict]:
    """envN's family list, from its core's own database: [{"id", "name", "role"}] (the role's name; "" for none).
    Empty when the core has no database yet."""
    db = data_dir(env) / "core" / "default" / "db" / "workspace.db"
    if not db.exists():
        return []
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        rows = con.execute("select p.person_id, p.name, coalesce(r.name, '') from people p "
                           "left join roles r on r.role_id = p.role_id order by p.name").fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()
    return [{"id": r[0], "name": r[1], "role": r[2]} for r in rows]


def sign_in_of(env: int) -> dict:
    """envN's sign-in, as asked: its working task's (the person found in the environment's own family list; nobody
    found: on, and said); an environment no task holds keeps what its file says."""
    held = next((t for t in load_tasks() if t.state == "working" and t.env == env), None)
    if not held:
        return (switches.read(data_dir(env)) or {}).get("sign_in") or dict(switches.SIGN_IN_ON)
    if held.sign_in != switches.board.AS:
        return switches.sign_in(held.sign_in)
    person = switches.find_person(people_of(env), held.sign_in_as)
    if person is None:
        say(f"  ! nobody in env{env}'s family list is {held.sign_in_as!r} (or more than one is): sign-in stays on")
    return switches.sign_in(switches.board.AS, person)


def sign_in_env(env: int) -> dict[str, str | None]:
    """The apps' AUTH line in envN: off only where sign-in is off there (everyone is the owner); else none, so
    sign-in is on and the core says who everyone is."""
    return {"AUTH": "off" if sign_in_of(env)["mode"] == switches.board.OFF else None}


def write_env_dev(env: int) -> None:
    """Each app's .env.dev in envN: env0's, with this environment's data folder, no sends or HA's automatic writes,
    sign-in on; real systems as the task asks (data.env_overrides: None drops env0's line)."""
    real = real_of(env)
    board = {switches.ENV: (data_dir(env) / switches.FILE).as_posix(), **switches.app_env(modes_of(env))}
    for app in APPS:
        src = repo_dir(0, app) / ".env.dev"
        if not src.exists():  # an app with no .env.dev (CodeHiro) takes its settings from up (apps.toml api_env)
            continue
        lines = src.read_text(encoding="utf-8").splitlines()
        forced = {**ENV_DEV_FORCED, **sign_in_env(env), **board, "DATA_DIR": (data_dir(env) / app).as_posix(),
                  **data.env_overrides(app, real, copy_lists())}
        keep = [ln for ln in lines if ln.split("=", 1)[0].strip() not in forced]
        keep += [f"{k}={v}" for k, v in forced.items() if v is not None]
        (repo_dir(env, app) / ".env.dev").write_text("\n".join(keep) + "\n", encoding="utf-8")


def board_of(env: int) -> tuple[str, dict[str, str]]:
    """envN's switchboard, as asked: its working task's preset and changes; an environment no task holds keeps what
    its file says (a switch made from its card), else the default preset."""
    held = next((t for t in load_tasks() if t.state == "working" and t.env == env), None)
    if held:
        return held.preset, dict(held.switches)
    rec = switches.read(data_dir(env)) or {}
    return rec.get("preset") or switches.DEFAULT, dict(rec.get("changes") or {})


def modes_of(env: int) -> dict[str, str]:
    """Each outside system's mode in envN (switches.py); a preset that is gone falls back to the default."""
    name, changes = board_of(env)
    try:
        return switches.resolve(name, changes)
    except switches.SwitchError:
        return switches.resolve(switches.DEFAULT)


def write_board(env: int) -> dict:
    """envN's switchboard file, from what was asked; its servers read it at start."""
    name, changes = board_of(env)
    who = sign_in_of(env)
    try:
        return switches.write(data_dir(env), env, name, changes, sign_in=who)
    except switches.SwitchError as exc:
        say(f"  ! {exc}: {switches.DEFAULT} instead")
        return switches.write(data_dir(env), env, switches.DEFAULT, sign_in=who)


def real_of(env: int) -> list[str]:
    """What envN's copy keeps of the real systems, in the copy lists' words (reads, writes, ai), worked out from its
    switchboard; none for env0, which is real already."""
    return switches.real_of(modes_of(env)) if env else []


def set_setting(db: Path, key: str, value: str) -> None:
    with sqlite3.connect(db) as con:
        con.execute("insert into setting(key, value) values (?, ?) on conflict(key) do update set value = excluded.value",
                    (key, value))


def configure_apps(env: int, apps: list[appfile.App]) -> None:
    """Point apps at this environment, env0 too: the link to its core, the core's admin, and the app's own address on
    this environment's dev site, where the one sign-in sends people back (never the live name an app claims by
    default). Run by configure and by every `up`, before the app starts; an app whose database doesn't exist yet gets
    them on the next `up`."""
    p = ports(env)
    for a in apps:
        db = app_data(env, a) / a.settings_db
        if not db.exists():
            continue
        with sqlite3.connect(db) as con:
            if not con.execute("select 1 from sqlite_master where name = 'setting'").fetchone():
                continue
        set_setting(db, "hiroleague_url", f"ws://127.0.0.1:{p['core-socket']}")
        set_setting(db, "hiroleague_admin_url", f"http://127.0.0.1:{p['core-ui']}")
        set_setting(db, a.site_key, f"http://127.0.0.1:{p[a.repo + '-ui']}")


def configure(env: int, task: str | None = None) -> None:
    """Point an environment's copies at its own ports: the core's listeners (its workspace's config.json), each
    app's link to the core. In env1..env5 also: the copied WhatsApp channel off (two clients on one account break
    it), LAN names off, and the core's workspace registered under its own name. Every environment: each repo's
    .claude/launch.json (write_launch)."""
    p = ports(env)
    with step(task, env, "configure"):
        ws = data_dir(env) / "core" / "default"
        cfg_path = ws / "config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg.update(http_port=p["core-http"], admin_port=p["core-admin"], extension_port=p["core-socket"])
        cfg.pop("plugin_port", None)  # the channel plugins sign in on the extension socket: no port of their own
        # Device chat: the core runs its own gateway on the environment's port, and devices pair to it there (the
        # device web app on this PC; a phone reaches only live's, by its LAN name)
        cfg.update(gateway_builtin=True, gateway_port=p["core-gateway"], gateway_url=f"ws://127.0.0.1:{p['core-gateway']}")
        # Left out rather than null: the core's config takes these as text when present (extension_host absent =
        # loopback; no LAN names in env1..env5)
        for key in ("extension_host", *(("site_names_ip",) if env else ())):
            if cfg.get(key) is None or env:
                cfg.pop(key, None)
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        configure_apps(env, appfile.APPS)
        if env:
            if workspace_name(env) not in registry_names():
                run(["uv", "run", "hiro", "workspaces", "create", workspace_name(env), "--path", str(ws)],
                    cwd=repo_dir(env, "hiroleague") / "hiroserver")
            # Real systems off unless the task asks, as the copy lists say (the core's turns the WhatsApp channel
            # off: two clients on one account break it): run on every configure, the copy may be fresh
            for line in data.make_safe(data_dir(env), real_of(env), copy_lists(),
                                       data.read_store(sys.modules[__name__])):
                say(f"  {line}")
        write_launch(env)


def launch_configs(env: int) -> dict[str, list[dict]]:
    """Each repo's servers for the browser pane (its .claude/launch.json): the environment's own addresses, with no
    command, so the pane only opens a server `hiro-work up` started in the environment's window and never starts one
    itself (servers run outside Claude, workflow.md). A repo with no server gets no file."""
    out: dict[str, list[dict]] = {}
    for s in servers(env).values():
        repo = s.cwd.relative_to(env_dir(env)).parts[0]
        out.setdefault(repo, []).append({"name": s.name, "url": f"http://127.0.0.1:{s.port}", "port": s.port})
    return out


def write_launch(env: int) -> None:
    """Write each repo's .claude/launch.json from launch_configs(), kept out of git through the repo's
    info/exclude (shared by every environment's worktree), since its ports differ per environment."""
    for repo, configs in launch_configs(env).items():
        d = repo_dir(env, repo)
        if not (d / ".git").exists():
            continue
        (d / ".claude").mkdir(exist_ok=True)
        (d / ".claude" / "launch.json").write_text(
            json.dumps({"version": "0.0.1", "configurations": configs}, indent=2) + "\n", encoding="utf-8")
        exclude = d / git(d, "rev-parse", "--git-path", "info/exclude")
        lines = exclude.read_text(encoding="utf-8").splitlines() if exclude.exists() else []
        if ".claude/launch.json" not in lines:
            exclude.parent.mkdir(parents=True, exist_ok=True)
            exclude.write_text("\n".join([*lines, ".claude/launch.json"]) + "\n", encoding="utf-8")


def registry_names() -> set[str]:
    reg = Path(os.environ["LOCALAPPDATA"]) / "hiro" / "registry.json"
    return {w["name"] for w in json.loads(reg.read_text(encoding="utf-8"))["workspaces"].values()}


def remove_tree(path: Path) -> None:
    """shutil.rmtree that also removes read-only files: git marks its pack files read-only on Windows, and CodeHiro's
    data holds git mirrors, so a plain rmtree stops on them."""
    def writable_then_retry(func, p, _exc):
        os.chmod(p, 0o666)
        func(p)
    shutil.rmtree(path, onexc=writable_then_retry)


def refresh_data(env: int, task: str | None = None, source: str = "env0") -> None:
    """envN's data, from where its task says (workflow.md, Data and real systems; data.SOURCES):
    - env0 (the default): env0's, as each repo's copy list says: the databases copied, the pictures hard-linked, the
      rest left out. Removing the old folder first removes only its links: env0's pictures stay.
    - live (or live:<stamp>): the same, then the databases rebuilt from a live copy (the latest when younger than an
      hour, else a new fetch), with the environment's per-place rows put back, as an apply does in env0.
    - vanilla: a fresh install: empty folders, the core's settings at their defaults; each app makes its database at
      its first start, and `up` pairs it and points it at the core.
    The source is recorded in the data folder (data.write_source), which the PC's helper tells CodeHiro."""
    if env == 0:
        return
    kind, stamp = data.parse_source(source)
    lists = copy_lists()
    for group in [*APPS, data.CORE]:
        if group == data.CORE:
            src, dst = data_dir(0) / "core" / "default", data_dir(env) / "core" / "default"
        else:
            src, dst = app_data(0, appfile.BY_REPO[group]), data_dir(env) / group
        with step(task, env, "data copy", group):
            if dst.exists():
                remove_tree(dst)
            dst.mkdir(parents=True)
            if kind == "vanilla":
                if group == data.CORE:
                    (dst / "config.json").write_text("{}", encoding="utf-8")  # the defaults; configure sets ports
                continue
            for line in data.copy_group(src, dst, group, lists):
                say(f"  {line}")
    if kind == "live":
        with step(task, env, "data copy", "live copy"):
            copy = data.fresh_copy(sys.modules[__name__], lists, stamp)
            for line in data.copy_live_into(sys.modules[__name__], env, copy, lists):
                say(f"  {line}")
        rec = data.write_source(sys.modules[__name__], env, "live", copy.name, data.stamp_time(copy.name))
    elif kind == "vanilla":
        rec = data.write_source(sys.modules[__name__], env, "vanilla")
    else:
        env0 = data.read_source(sys.modules[__name__], 0) or {}
        rec = data.write_source(sys.modules[__name__], env, "env0", env0.get("stamp"), env0.get("live_at"))
    board = write_board(env)
    write_env_dev(env)
    configure(env, task)
    say(f"  {data.describe_source(rec)}")
    say(f"  {switches.describe(board)}")


def fetch_all(repos: list[str], task: str | None, env: int | None) -> None:
    """`git fetch origin` in env0's repos, side by side: one after another they took about 1.4 s each, most of a
    start's time. A fetch that fails changes nothing here: fresh_base then uses env0's dev/main as it is."""
    with step(task, env, "fetch"), ThreadPoolExecutor(max_workers=len(repos) or 1) as pool:
        list(pool.map(lambda r: git(repo_dir(0, r), "fetch", "-q", "origin", check=False), repos))


def fresh_base(repo: str, task: str | None, fetch: bool = True) -> str:
    """A repo's base for a new branch: env0's dev/main, first brought up to GitHub when it can fast-forward.
    ``fetch=False`` when fetch_all has just fetched it."""
    d = repo_dir(0, repo)
    if fetch:
        git(d, "fetch", "-q", "origin", check=False)
    main = main_of(repo)
    behind = int(git(d, "rev-list", "--count", f"{main}..origin/{main}", check=False) or 0)
    if behind:
        branch = git(d, "branch", "--show-current")
        # A fast-forward that would touch someone's uncommitted edits is refused by git: env0's dev/main is then
        # used as it is, and the branch catches up with GitHub when it merges.
        moved = branch == main and subprocess.run(
            ["git", "-C", str(d), "merge", "--ff-only", "-q", f"origin/{main}"], capture_output=True).returncode == 0
        if not moved:
            say(f"  ! env0's {repo} is {behind} commit(s) behind GitHub and wasn't brought up: its {main} is used.")
    return git(d, "rev-parse", main)


# ----------------------------------------------------------------------------------------------- a plan's branch


def branch_tip(repo: str, branch: str) -> str:
    """A branch's commit in a repo ("" when it has none). Every environment's worktree shares env0's branches."""
    return git(repo_dir(0, repo), "rev-parse", "--verify", "-q", f"refs/heads/{branch}", check=False)


def is_ancestor(repo_path: Path, older: str, newer: str) -> bool:
    return subprocess.run(["git", "-C", str(repo_path), "merge-base", "--is-ancestor", older, newer],
                          capture_output=True, creationflags=NO_WINDOW).returncode == 0


def sits_on(repo: str, branch: str) -> list[str]:
    """The folders that have a branch checked out, in any worktree of the repo."""
    out, folder = [], ""
    for line in git(repo_dir(0, repo), "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            folder = line.removeprefix("worktree ").replace("/", "\\")
        elif line == f"branch refs/heads/{branch}":
            out.append(folder)
    return out


def ensure_plan_branch(repo: str, branch: str) -> str:
    """The plan's branch in a repo, made from env0's dev/main when it has none there; its commit."""
    if at := branch_tip(repo, branch):
        return at
    main = git(repo_dir(0, repo), "rev-parse", main_of(repo))
    # "" as the old value: made only when nobody made it meanwhile (a phase starting beside this one); else theirs
    git(repo_dir(0, repo), "update-ref", f"refs/heads/{branch}", main, "", check=False)
    return branch_tip(repo, branch)


def unchecked_out(repo: str, branch: str) -> None:
    """Stop when a folder has the plan's branch checked out: moving it would leave that folder out of step (git
    update-ref moves a branch whatever sits on it)."""
    if held := sits_on(repo, branch):
        raise Stop(f"{repo}: {', '.join(held)} has {branch} checked out, and a plan's branch is never checked out. "
                   f"Move that folder off it (`git -C <folder> switch --detach {branch}`), then run this again.")


def move_plan_branch(repo: str, branch: str, new: str, old: str) -> None:
    """Move a plan's branch from ``old`` to ``new`` ("" old: make it), compare-and-swap: only forward, only from
    where it was read, and never under a folder that has it checked out. Two phases merging at once: the second is
    told to merge again."""
    unchecked_out(repo, branch)
    d = repo_dir(0, repo)
    if old and not is_ancestor(d, old, new):
        raise Stop(f"{repo}: {branch} moved since this read it (another phase merged into it): merge again.")
    out = subprocess.run(["git", "-C", str(d), "update-ref", f"refs/heads/{branch}", new, old], capture_output=True,
                         text=True, creationflags=NO_WINDOW)
    if out.returncode != 0:
        raise Stop(f"{repo}: {branch} moved since this read it (another phase merged into it): merge again.")


# Where a plan's branch is copied off the PC: each repo's bare repo on Simone (the `server` remote), whose deploy hook
# ignores every branch but main. The copy is a note when it fails (Simone away), never a stop.
COPY_REMOTE = "server"
COPY_TIMEOUT_S = 60


def copy_off(repo: str, branch: str, delete: bool = False) -> str | None:
    """Copy a plan's branch (or a set-aside one) to the repo's bare repo on Simone, as it is here now, or remove it
    there (``delete``). Returns a note when it couldn't, else None. A plan's branch can hold weeks of work that exists
    nowhere else until it lands."""
    spec = f":refs/heads/{branch}" if delete else f"+refs/heads/{branch}:refs/heads/{branch}"
    # git's own variables are dropped: run from a commit's hook, GIT_DIR would push the committing repo instead
    clean = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") or k == "GIT_EXEC_PATH"}
    try:
        out = subprocess.run(["git", "-C", str(repo_dir(0, repo)), "push", "-q", COPY_REMOTE, spec],
                             capture_output=True, text=True, timeout=COPY_TIMEOUT_S, env=clean,
                             creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"{repo}: {branch} not copied to Simone ({exc.__class__.__name__}); it is copied at its next move"
    if out.returncode != 0 and not (delete and "remote ref does not exist" in out.stderr):
        why = (out.stderr.strip().splitlines() or ["no answer"])[-1]
        return f"{repo}: {branch} not copied to Simone ({why}); it is copied at its next move"
    return None


def refresh_plan_branch(env: int, repo: str, branch: str) -> str | None:
    """Bring a plan's branch up to env0's dev/main, in the environment's folder of the repo (clean: the caller checks):
    detached on the branch, dev/main merged; clean, the branch moves to the merge (committed on the detached HEAD on
    purpose); a conflict is left for the task's next sync or merge, and said. The folder is left detached. Returns a
    note, or None when the branch holds dev/main already (or there is none)."""
    old = branch_tip(repo, branch)
    main = main_of(repo)
    if not old or is_ancestor(repo_dir(0, repo), git(repo_dir(0, repo), "rev-parse", main), old):
        return None
    d = repo_dir(env, repo)
    git(d, "switch", "-q", "--detach", old)
    out = subprocess.run(["git", "-C", str(d), "merge", "--no-edit", "-q", "-m", f"Merge {main} into {branch}", main],
                         capture_output=True, text=True, creationflags=NO_WINDOW)
    if out.returncode != 0:
        git(d, "merge", "--abort", check=False)
        return (f"{repo}: {branch} conflicts with {main}: left as it is; the task's next sync or merge brings {main} "
                "in, to resolve there")
    move_plan_branch(repo, branch, git(d, "rev-parse", "HEAD"), old)
    if note := copy_off(repo, branch):
        say(f"  {note}")
    return f"{repo}: {branch} brought up to {main}"


def follow_ref(task: Task, repo: str) -> str:
    """What a repo the task doesn't reserve sits on: its plan's branch where the plan has one in that repo, else
    dev/main."""
    return task.target if task.target and branch_tip(repo, task.target) else main_of(repo)


def release_others(env: int, task: Task) -> None:
    """A free environment sits on main: a task on a plan's branch leaves its other repos there too (they followed the
    plan's branch), each that is clean."""
    if not task.target:
        return
    for repo in REPOS:
        d = repo_dir(env, repo)
        if repo not in task.repos and (d / ".git").exists() and not dirty(d):
            git(d, "switch", "-q", "--detach", main_of(repo))


def named_task(value: str) -> dict:
    """The record of the task an id names (open or ended), or {}."""
    for p in (task_path(value), TASKS / "done" / f"{value}.json"):
        if value and p.exists():
            with contextlib.suppress(OSError, ValueError):
                return json.loads(p.read_text(encoding="utf-8"))
    return {}


def plan_target(part_of: str | None, on_main: bool) -> tuple[str, str, str]:
    """(part_of, plan, target) for a new task. A plan that ships whole is its target, unless --on-main; --part-of
    naming a task on a plan's branch takes that task's plan and target. A plan/<name> branch for a plan not recorded
    as shipping whole stops the start: its work would go to main by accident."""
    import plan

    value = (part_of or "").strip()
    name = part_of_name(value)
    rec = named_task(value)
    if rec.get("target") and not on_main:
        return rec.get("plan") or name, rec.get("plan") or name, rec["target"]
    branch = plan.branch_of(name)
    if branch:
        return name, ("" if on_main else name), ("" if on_main else branch)
    if name and not on_main:
        try:
            wanted = plan.branch_name(name)
        except Stop:
            return name, "", ""
        found = [r for r in REPOS if branch_tip(r, wanted)]
        if found:
            raise Stop(f"{wanted} exists in {', '.join(found)}, but plan {name} isn't recorded as shipping whole. Send "
                       "the plan with \"ships\": \"whole\" to work on that branch, or start with --on-main to go to "
                       "main.")
    return name, "", ""


# ------------------------------------------------------------------------------------------------------- the verbs


def part_of_name(value: str | None) -> str:
    """--part-of as given: a task's id (open or done) stands for its title; anything else is the name itself."""
    value = (value or "").strip()
    for p in (task_path(value), TASKS / "done" / f"{value}.json"):
        if value and p.exists():
            with contextlib.suppress(OSError, ValueError):
                return json.loads(p.read_text(encoding="utf-8")).get("title") or value
    return value


def plan_base(env: int, repo: str, task: Task) -> str:
    """Where a task on a plan's branch starts in a repo it reserves: the plan's branch, made from main when the repo
    has none, and brought up to main first when that merges cleanly (in the environment's clean folder)."""
    ensure_plan_branch(repo, task.target)
    if note := refresh_plan_branch(env, repo, task.target):
        say(f"  {note}")
    return branch_tip(repo, task.target)


def cmd_start(a) -> None:
    with locked():
        tasks = load_tasks()
        if task_path(a.task).exists():
            raise Stop(f"Task '{a.task}' is already open.")
        repos = expand(a.repos.split(","), a.kit)
        part_of, plan_name, target = plan_target(a.part_of, getattr(a, "on_main", False))
        phase = getattr(a, "phase", None)
        if phase:
            import plan

            plan.phase_to_join(part_of, phase)  # a phase that isn't there, or is done, stops before any reserve
        # A phase of a plan that ships whole never stops for the plan's other open tasks: each phase is a task, on the
        # plan's branch. Elsewhere a phase beside an open one says --own-branch, and a step joins that task
        same = [] if a.own_branch or target else same_work(a.part_of or "", tasks)
        if same:
            raise Stop("Part of open work already: " + ", ".join(f"{t.id} ({t.title}, "
                                                                 + (f"env{t.env}" if t.env else "paused") + ")"
                                                                 for t in same)
                       + ". A phase of it is a task of its own: start again with --own-branch. A step of it joins that "
                       "task, on its branch: `python C:\\hiro\\env0\\hiro-docs\\standards\\tools\\guard.py join <task>` "
                       "(and `hiro-work reserve <task> <repo>` for one more repo).")
        env = pick_env(tasks, a.env)
        task = Task(id=a.task, title=a.title or a.task, env=env, repos=repos,
                    preset=switches.preset(a.preset)["name"], switches=switches.parse_sets(a.set or []),
                    sign_in="as" if a.as_person else "off" if a.quick_sign_in else "on", sign_in_as=a.as_person or "",
                    part_of=part_of, about=(a.about or "").strip(), data=a.data, target=target, plan=plan_name,
                    lands=getattr(a, "lands", "") or "", lands_phases=list(getattr(a, "lands_phases", None) or []),
                    created=datetime.now().astimezone().isoformat(timespec="seconds"))
        save(task)  # the reservation holds from here
    event(task=task.id, env=env, step="task", phase="start", repos=repos, title=task.title,
          **({"part_of": task.part_of} if task.part_of else {}), **({"about": task.about} if task.about else {}),
          **({"lands": task.lands} if task.lands else {}))
    try:
        init_env(env, task.id)
        fetch_all(REPOS, task.id, env)
        for repo in REPOS:
            base = fresh_base(repo, task.id, fetch=False)
            d = repo_dir(env, repo)
            if dirty(d):
                raise Stop(f"env{env}'s {repo} has uncommitted files: it isn't free (hiro-work sweep).")
            with step(task.id, env, "switch", repo):
                if repo in repos:
                    if task.target:  # the task's branch starts from its plan's, brought up to main when it can be
                        base = plan_base(env, repo, task)
                    git(d, "switch", "-q", "-C", task.branch, base)
                    task.base[repo] = base
                else:
                    git(d, "switch", "-q", "--detach", follow_ref(task, repo) if task.target else base)
        install_all(env, REPOS, task.id)
        refresh_data(env, task.id, task.data)
        save(task)
    except BaseException:
        with locked():
            task_path(task.id).unlink(missing_ok=True)  # no half-made reservation
        raise
    card(task)
    say_overlaps(task)
    if not task.lands:  # a landing is no phase: plan.landed moves the phases it brings
        import plan

        for line in plan.started(task.id, part_of, phase, open_ids("working", "paused") - {task.id}):
            say(line)


# ----------------------------------------------------------------------------------- reservations at every step (fresh)


def overlaps(task: Task, tasks: list[Task] | None = None) -> list[str]:
    """Other open tasks that change what this one does: the same repos, or the core's kits beside an app that reads
    them. Said at every solid step (start, each commit, sync, merge), since another task can start at any time."""
    out = []
    mine = set(task.repos)
    for other in tasks if tasks is not None else load_tasks():
        if other.id == task.id or other.state != "working":
            continue
        theirs = set(other.repos)
        shared = sorted(mine & theirs)
        kit = ("hiroleague" in mine and theirs & set(KIT_READERS)) or ("hiroleague" in theirs and mine & set(
            KIT_READERS))
        if shared or kit:
            what = ", ".join(shared) if shared else "the core's kits and an app that reads them"
            out.append(f"{what}: also changed by {other.id} (env{other.env}, {other.title})")
    return out


def say_overlaps(task: Task) -> None:
    for line in overlaps(task):
        say(f"  note: {line}. Whichever merges second merges the other's work first.")


def bring_up_others(env: int, task: Task) -> list[str]:
    """An environment's repos its task doesn't reserve follow env0: each moves forward to env0's dev/main when it is
    clean and behind, so checks read today's core and kits (a kit changed in env0 meanwhile, as on Mon, Nov 16, 2026,
    broke a merge in env1). A task on a plan's branch follows that branch where the repo has one, brought up to main
    first when it merges cleanly, so it builds against the plan's kits. A repo with uncommitted files is left as it
    is, and said."""
    if not env:
        return []
    notes = []
    for repo in REPOS:
        d = repo_dir(env, repo)
        if repo in task.repos or not (d / ".git").exists():
            continue
        if dirty(d):
            notes.append(f"{repo}: has uncommitted files, left as it is")
            continue
        ref = follow_ref(task, repo)
        if ref != main_of(repo) and (note := refresh_plan_branch(env, repo, ref)):
            notes.append(note)
        where = f"env0's {ref}" if ref == main_of(repo) else ref
        target = git(repo_dir(0, repo), "rev-parse", ref)
        head = git(d, "rev-parse", "HEAD")
        if head == target:
            continue
        ahead = subprocess.run(["git", "-C", str(d), "merge-base", "--is-ancestor", head, target]).returncode == 0
        if not ahead:
            notes.append(f"{repo}: not behind {where}, left as it is")
            continue
        git(d, "switch", "-q", "--detach", target)
        notes.append(f"{repo}: brought up to {where} ({target[:8]})")
    return notes


def task_for_dir(path: Path) -> tuple[int, str, Task | None] | None:
    """The environment, repo and working task that reserves it, for a folder inside C:\\hiro\\envN\\<repo>."""
    try:
        rel = path.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return None
    parts = rel.parts
    if len(parts) < 2 or not parts[0].startswith("env") or not parts[0][3:].isdigit() or parts[1] not in REPOS:
        return None
    env, repo = int(parts[0][3:]), parts[1]
    owner = next((t for t in load_tasks() if t.state == "working" and t.env == env and repo in t.repos), None)
    return env, repo, owner


def cmd_fresh(a) -> None:
    """The commit hook's step (build-kit/git-hooks/pre-commit): a commit belongs to a task that reserves the repo here;
    other tasks on the same repos are named; the environment's other repos follow env0 before the check runs."""
    # git's own variables are dropped, as copy_off does: a commit in a worktree runs its hook with GIT_DIR and
    # GIT_INDEX_FILE set to the committing repo, and they win over `git -C <other repo>`. Read through them, every
    # other repo looked changed ("has uncommitted files") and none followed env0 before the check.
    for name in [n for n in os.environ if n.startswith("GIT_") and n != "GIT_EXEC_PATH"]:
        del os.environ[name]
    found = task_for_dir(Path(a.path))
    if found is None:
        return  # not a Hiro environment's repo
    env, repo, task = found
    if task is None:
        raise Stop(f"no task reserves env{env}'s {repo}: a commit belongs to a task. Start one "
                   f"(`C:\\hiro\\bin\\hiro-work.cmd start <task> --repos {repo}`), or add the repo to yours "
                   f"(`C:\\hiro\\bin\\hiro-work.cmd reserve <task> {repo}`).")
    say_overlaps(task)
    for line in bring_up_others(env, task):
        say(f"  {line}")


def cmd_reserve(a) -> None:
    """Add repos to an open task (a change turned out to reach one more repo), free in its environment."""
    with locked():
        task = get(a.task)
        if task.state != "working" or task.env is None:
            raise Stop(f"Task {task.id} isn't working in an environment (it is {task.state}).")
        new = [r for r in expand(a.repos.split(","), a.kit) if r not in task.repos]
        if not new:
            say(f"Task {task.id} reserves {', '.join(task.repos)} already.")
            return
        held = {r: t for r, t in reserved_in(task.env, load_tasks()).items() if r in new and t != task.id}
        if held:
            raise Stop("Reserved already: " + ", ".join(f"{r} by {t}" for r, t in held.items()) + ".")
        env = task.env
        for repo in new:
            d = repo_dir(env, repo)
            if dirty(d):
                raise Stop(f"env{env}'s {repo} has uncommitted files: it isn't free (hiro-work sweep).")
            base = fresh_base(repo, task.id)
            if task.target:
                base = plan_base(env, repo, task)
            git(d, "switch", "-q", "-C", task.branch, base)
            task.base[repo] = base
            task.repos.append(repo)
        save(task)
    event(task=task.id, env=task.env, step="reserve", phase="end", ok=True, repos=new)
    say(f"Task {task.id} now reserves {', '.join(task.repos)}.")
    say_overlaps(task)


def card(task: Task) -> None:
    p = ports(task.env) if task.env is not None else {}
    where = env_dir(task.env) if task.env is not None else "(paused)"
    say("")
    say(f"Task {task.id}" + (f" (part of {task.part_of})" if task.part_of else "")
        + f": env{task.env} | reserves {', '.join(task.repos)} | {where}")
    if task.about:
        say(f"  {task.about}")
    if task.env:
        into = f", into {task.target}" if task.target else ""
        say(f"  branch {task.branch}{into} | data {data_dir(task.env)} | ports {min(p.values())}-{min(p.values()) + appfile.BLOCK - 1}")
        rec = switches.read(data_dir(task.env))
        say(f"  {switches.describe(rec)} | {switches.describe_sign_in(rec)}")
        say(f"  {data.describe_source(data.read_source(sys.modules[__name__], task.env))}")


def cmd_configure(a) -> None:
    """Point an environment at its ports; with --data, a free env1..env5 gets env0's data again first (its switches
    as it has them), as a task's start would copy it."""
    if not a.data:
        configure(a.env)
        return
    if not a.env:
        raise Stop("env0's data is Michel's own: refresh-data brings live's into it.")
    held = [t.id for t in load_tasks() if t.state == "working" and t.env == a.env]
    if held:
        raise Stop(f"env{a.env} is {held[0]}'s: hiro-work data {a.env} env0 copies its data again.")
    up = [n for n, s in servers(a.env).items() if listening(s.port)]
    if up:
        raise Stop(f"env{a.env}'s servers are up ({', '.join(up)}): hiro-work down {a.env} first.")
    refresh_data(a.env)
    say(f"env{a.env}: {switches.describe(switches.read(data_dir(a.env)))}")


def cmd_switch(a) -> None:
    """hiro-work switch <env> [--preset NAME] [--set system=mode ...] [--sign-in on|off | --as PERSON]: what envN
    reaches of each outside system, and its sign-in (off: everyone is the owner; --as: everyone is that person of its
    family list). With nothing to change it only shows. Else its servers must be down: the switchboard is written, the data copied again
    (what a copy keeps of logins and keys follows it), and the task working there keeps the choice."""
    env = a.env
    if not env:
        raise Stop("env0 is Michel's own: its settings decide what it reaches.")
    if a.sign_in and a.as_person:
        raise Stop("--sign-in or --as, not both.")
    who = ("as", a.as_person) if a.as_person else (a.sign_in, "") if a.sign_in else None
    if who and who[0] == "as" and switches.find_person(people_of(env), who[1]) is None:
        raise Stop(f"Nobody in env{env}'s family list is {who[1]!r} (or more than one is). Its people: "
                   + (", ".join(f"{p['name']} ({p['role'] or 'no role'})" for p in people_of(env)) or "none") + ".")
    if not a.preset and not a.set and not who:
        rec = switches.read(data_dir(env))
        say(f"env{env}: {switches.describe(rec)} | {switches.describe_sign_in(rec)}")
        for system, (name, _modes) in switches.SYSTEMS.items():
            say(f"  {name:22} {(rec or {}).get('modes', {}).get(system, '-')}")
        return
    name, changes = board_of(env)
    try:
        if a.preset:  # a new preset starts clean: the old changes belonged to the old one
            name, changes = switches.preset(a.preset)["name"], {}
        changes = {**changes, **switches.parse_sets(a.set or [])}
        base = switches.preset(name)["modes"]
        changes = {k: v for k, v in changes.items() if base[k] != v}
    except switches.SwitchError as exc:
        raise Stop(str(exc)) from exc
    up = [n for n, s in servers(env).items() if listening(s.port)]
    if up and not a.restart:
        raise Stop(f"env{env}'s servers are up ({', '.join(up)}): hiro-work down {env} first, or --restart.")
    held = next((t for t in load_tasks() if t.state == "working" and t.env == env), None)
    before = set(real_of(env))
    if up:
        servers_down(env, up)
    if held:
        with locked():
            held.preset, held.switches = name, changes
            if who:
                held.sign_in, held.sign_in_as = who
            save(held)
    else:
        kept = (switches.read(data_dir(env)) or {}).get("sign_in")
        if who:
            kept = switches.sign_in(who[0], switches.find_person(people_of(env), who[1]))
        switches.write(data_dir(env), env, name, changes, sign_in=kept)
    opened = set(real_of(env)) - before
    if opened:
        # A system that was closed opens: its addresses and logins were taken out of the copy, so the data is copied
        # again from its source (what the task made there goes)
        say(f"env{env}: {', '.join(sorted(opened))} open now, so its data is copied again.")
        refresh_data(env, held.id if held else None, held.data if held else "env0")
    else:
        # Nothing opens: the data stays; the file, the apps' lines and what is turned off follow
        board = write_board(env)
        write_env_dev(env)
        configure(env, held.id if held else None)
        say(f"env{env}: {switches.describe(board)} | {switches.describe_sign_in(board)}")
    event(task=held.id if held else None, env=env, step="switch", phase="end", ok=True, preset=name, changes=changes,
          sign_in=sign_in_of(env)["mode"])
    if up:
        cmd_up(type("A", (), {"env": env, "servers": up, "wait": 120})())


def cmd_preset(a) -> None:
    """hiro-work preset list | save <name> --from <env> | remove <name>: the switchboard's presets (presets.toml)."""
    try:
        if a.what == "save":
            if a.from_env:
                modes = modes_of(a.from_env)
            elif a.preset:
                modes = switches.resolve(a.preset, switches.parse_sets(a.set or []))
            else:
                raise Stop("Say what to save: --from <env> (its switchboard), or --preset <name> with --set changes.")
            switches.save_preset(a.name, modes, a.about or "")
            say(f"Saved {a.name!r}: hiro-work start --preset \"{a.name}\", or switch <env> --preset \"{a.name}\".")
        elif a.what == "remove":
            switches.remove_preset(a.name)
            say(f"Removed {a.name!r}.")
    except switches.SwitchError as exc:
        raise Stop(str(exc)) from exc
    for p in switches.presets():
        real = [switches.SYSTEMS[k][0] for k, m in p["modes"].items() if m == "real"]
        say(f"  {p['name']:24} {'built in' if p['builtin'] else 'yours':9} real: {', '.join(real) or 'nothing'}")


def cmd_data(a) -> None:
    """hiro-work data <env> <source>: an environment's data again, from env0, vanilla or a live copy (servers down);
    the task working there keeps that source for its later copies (resume, real)."""
    try:
        data.parse_source(a.source)
    except ValueError as exc:
        raise Stop(str(exc)) from exc
    if not a.env:
        raise Stop("env0's data comes from live: hiro-work refresh-data --now.")
    if not (env_dir(a.env) / "hiroleague" / ".git").exists():
        raise Stop(f"env{a.env} isn't made yet (hiro-work init {a.env}).")
    up = [n for n, s in servers(a.env).items() if listening(s.port)]
    if up:
        raise Stop(f"env{a.env}'s servers are up ({', '.join(up)}): hiro-work down {a.env} first.")
    held = next((t for t in load_tasks() if t.state == "working" and t.env == a.env), None)
    if held:
        with locked():
            held.data = a.source
            save(held)
    refresh_data(a.env, held.id if held else None, a.source)


def kit_changed(env: int, task: Task) -> bool:
    if "hiroleague" not in task.repos:
        return False
    base = task.base.get("hiroleague")
    changed = git(repo_dir(env, "hiroleague"), "diff", "--name-only", f"{base}..HEAD", "--", *KIT_PATHS)
    return bool(changed)


def cmd_merge(a) -> None:
    task = get(a.task)
    env = task.env
    if not env:
        raise Stop(f"Task {task.id} is paused: resume it first (hiro-work resume {task.id}).")
    for repo in task.repos:
        if dirty(repo_dir(env, repo)):
            raise Stop(f"env{env}'s {repo} has uncommitted files: commit them on {task.branch} first.")
    for repo, at in task.landed.items():
        # A landing whose conflict was resolved by hand: its branch must hold what plan land took
        if not is_ancestor(repo_dir(env, repo), at, task.branch):
            raise Stop(f"{repo}: {task.branch} doesn't hold {task.lands} as plan land took it ({at[:8]}). In "
                       f"{repo_dir(env, repo)}: git merge --no-ff -m \"Land {task.part_of}\" {at}, resolve, commit, "
                       f"then merge again.")
    say_overlaps(task)
    # Merging is one step with its own inside (CodeHiro shows the task as merging while it runs)
    with step(task.id, env, "merge"):
        for line in bring_up_others(env, task):
            say(f"  {line}")
        waiting = merge_steps(task, env)
        if task.lands:
            for line in after_landing(task):
                say(f"  {line}")
    # 4. Release the environment, keep it warm
    for repo in task.repos:
        d = repo_dir(env, repo)
        git(d, "switch", "-q", "--detach", main_of(repo))
        git(d, "branch", "-q", "-D", task.branch)
    release_others(env, task)
    with step(task.id, env, "servers down"):
        servers_down(env)
    with locked():
        task.state = "done"
        save(task)
    event(task=task.id, env=env, step="task", phase="end", ok=True, merged=True,
          **({"into": task.target, "plan": task.plan} if task.target else {}),
          **({"lands": task.lands, "plan": task.part_of} if task.lands else {}))
    if task.target:
        follow_plans(task.id, "inplan", ("working", "review"), open_ids("working", "paused"))
        say(f"Task {task.id} merged into {task.target} (plan {task.plan}): {', '.join(task.repos)}; env0's main is "
            f"untouched and env{env} is free. Its work reaches main when the plan lands.")
    else:
        follow_plans(task.id, "merged", ("working", "review"), open_ids("working", "paused"))
        say(f"Task {task.id} merged: {', '.join(task.repos)} in env0; env{env} is free. Not pushed: the deploy "
            "pushes.")
    if waiting:
        say(waiting_installs_note(waiting))


def cmd_sync(a) -> None:
    """Merge the latest dev/main (GitHub's, then env0's) into the task's branches without merging the task: a task that(
)    runs for long stays close to main, so its merge brings in little. Nothing is checked or shipped here; the commit's
    hook checks the merge when the task next commits, and the merge checks everything."""
    task = get(a.task)
    env = task.env
    if not env:
        raise Stop(f"Task {task.id} is paused: resume it first (hiro-work resume {task.id}).")
    for repo in task.repos:
        if dirty(repo_dir(env, repo)):
            raise Stop(f"env{env}'s {repo} has uncommitted files: commit them on {task.branch} first.")
    say_overlaps(task)
    with step(task.id, env, "sync"):
        for line in bring_up_others(env, task):
            say(f"  {line}")
        merge_latest(task, env, then="sync")
        held = sorted({n for r in REPOS for n in install(env, r, task.id, spare_servers=True)})
    say(f"Task {task.id} is up to main: {', '.join(task.repos)} merged on {task.branch}.")
    if held:
        names = " ".join(held)
        say(f"env{env}'s {', '.join(held)} run on packages that changed: hiro-work down {env} {names}, then "
            f"hiro-work install {env}, then hiro-work up {env} {names}.")


def merge_latest(task: Task, env: int, then: str = "merge") -> None:
    """Bring each of the task's branches up to GitHub and to env0's dev/main, then to its plan's branch when it has one
    (``then``: the command to run again after a conflict is resolved)."""
    for repo in task.repos:
        d = repo_dir(env, repo)
        refs = [f"origin/{main_of(repo)}", main_of(repo), *([task.target] if task.target else [])]
        with step(task.id, env, "merge latest", repo):
            git(d, "fetch", "-q", "origin", check=False)
            for ref in refs:
                # A new app has no GitHub repo until its first deploy: a ref that doesn't exist is nothing to merge
                # (merging it would fail and read as a conflict)
                if not git(d, "rev-parse", "--verify", "-q", ref, check=False):
                    continue
                out = subprocess.run(["git", "-C", str(d), "merge", "--no-edit", "-q", ref], capture_output=True,
                                     text=True)
                if out.returncode != 0:
                    git(d, "merge", "--abort", check=False)
                    # A fix: a merge brings in origin/dev and then env0's dev. A resolve that merges only the first makes the merge
                    # merge the second after the commit hook's check, so every part of the check runs twice
                    if task.target:
                        raise Stop(f"{repo}: merging {ref} into {task.branch} conflicts. Resolve it in {d}: merge "
                                   f"{refs[0]}, {refs[1]} and {refs[2]} ({then} merges them in that order), then "
                                   f"commit, then {then} again.")
                    raise Stop(f"{repo}: merging {ref} into {task.branch} conflicts. Resolve it in {d}: merge both "
                               f"origin/{main_of(repo)} and {main_of(repo)} ({then} merges them in that order), "
                               f"then commit, then {then} again.")


def merge_steps(task: Task, env: int) -> dict[str, list[str]]:
    """Stop the servers, merge the latest, check, then fast-forward env0 (cmd_merge's own steps). Returns the env0
    installs left waiting because env0's dev server runs on those packages: {repo: [server names]}."""
    # A fix: the task's own servers stop before any install. A running Vite holds node_modules' native .node files
    # (lightningcss), and on Windows npm ci can't unlink them (EPERM), which failed the eval-app merge on Nov 17, 2026.
    # Only this environment's servers: env0's are Michel's and are never touched.
    with step(task.id, env, "servers down"):
        servers_down(env)
    # 1. Bring each branch up to GitHub and to env0's dev/main
    merge_latest(task, env)
    # 2. The checks: installs first, then the core's alone and two apps' at a time (check_repos)
    to_check = [r for r in task.repos if (repo_dir(env, r) / "scripts" / "check.sh").exists()]
    if kit_changed(env, task):
        to_check += [r for r in KIT_READERS if r not in to_check]
    for repo in to_check:
        install(env, repo, task.id)
    failed = check_repos(task, env, to_check)
    # Every copy list as it will be in env0: a wrong one would stop every later start, so it is refused here. Read by
    # the environment's own copylist.py, as each commit's check does: a fix, since main's parser refused a list
    # format the task itself brings ([[secret]] lines, Nov 18, 2026)
    with step(task.id, env, "copy lists") as outcome:
        parser = repo_dir(env, "hiroleague") / "build-kit" / "work" / "copylist.py"
        for repo in REPOS:
            if not (repo_dir(env, repo) / data.copylist.FILE).exists():
                continue
            out = subprocess.run([sys.executable, str(parser), str(repo_dir(env, repo))], capture_output=True,
                                 text=True, encoding="utf-8", errors="replace")
            if out.returncode != 0:
                failed.append(f"a copy list: {(out.stdout + out.stderr).strip()[-300:]}")
                outcome.fail(out.stdout.strip()[-300:])
    if failed:
        raise Stop("Checks failed: " + "; ".join(failed) + ". Fix, commit, merge again.")
    task.merged_at = {}
    if task.target:  # 3. the plan's branch moves to the task's; env0 isn't touched, so no install waits there
        into_plan(task, env)
        return {}
    # 3. dev/main moves to the branch; env0's checkouts follow (a fast-forward)
    waiting: dict[str, list[str]] = {}
    for repo in task.repos:
        with step(task.id, env, "fast-forward", repo):
            before = git(repo_dir(0, repo), "rev-parse", "HEAD")
            git(repo_dir(0, repo), "merge", "--ff-only", "-q", task.branch)
            if (after := git(repo_dir(0, repo), "rev-parse", "HEAD")) != before:
                task.merged_at[repo] = after
            # A landing's commits are recorded as landed: CodeHiro keeps them the work of the phases that brought them
            record_commits(task.id, env, repo, before, git(repo_dir(0, repo), "rev-parse", "HEAD"),
                           "land" if task.lands else "merge")
            # A fix: env0's servers are Michel's and merge never stops them, and npm ci under a running Vite fails
            # with EPERM after env0 has already moved. So that install waits (hiro-work install 0 <repo>).
            if held := install(0, repo, task.id, spare_servers=True):
                waiting[repo] = held
    return waiting


def after_landing(task: Task) -> list[str]:
    """After a landing's fast-forward: in each repo the plan's branch goes when main holds all of it (it exists only
    while it holds work main lacks); one a phase merged into meanwhile stays, and lands next time. The phases that
    were In the plan when it started are Merged."""
    import plan

    notes, kept = [], []
    for repo in task.landed:
        at = branch_tip(repo, task.lands)
        if not at:
            continue
        if is_ancestor(repo_dir(0, repo), at, git(repo_dir(0, repo), "rev-parse", main_of(repo))):
            git(repo_dir(0, repo), "update-ref", "-d", f"refs/heads/{task.lands}", at)
            if note := copy_off(repo, task.lands, delete=True):  # its copy on Simone goes with it
                notes.append(note)
        else:
            kept.append(repo)
    if kept:
        notes.append(f"{task.lands} kept in {', '.join(kept)}: a phase merged into it meanwhile; it lands next time")
    return notes + plan.landed(task)


def into_plan(task: Task, env: int) -> None:
    """A phase's merge into its plan's branch: in each reserved repo the branch moves to the task's, only when it is
    still where the merge read it (the task's branch holds it); otherwise nothing moves and the session merges again.
    Every repo is checked before any moves, under the tasks' lock (two phases can merge at once)."""
    with locked():
        moves = []
        for repo in task.repos:
            new, old = git(repo_dir(env, repo), "rev-parse", task.branch), branch_tip(repo, task.target)
            unchecked_out(repo, task.target)
            if old and not is_ancestor(repo_dir(0, repo), old, new):
                raise Stop(f"{repo}: {task.target} moved since this merge read it (another phase merged into it): "
                           "merge again.")
            moves.append((repo, new, old))
        for repo, new, old in moves:
            main = git(repo_dir(0, repo), "rev-parse", main_of(repo))
            if not old and is_ancestor(repo_dir(0, repo), new, main):
                continue  # nothing main lacks: a plan's branch exists only while it holds work
            with step(task.id, env, "into plan", repo):
                move_plan_branch(repo, task.target, new, old)
                record_commits(task.id, env, repo, old or main, new, "plan")
                task.merged_at[repo] = new
            with step(task.id, env, "copy off", repo) as outcome:
                if note := copy_off(repo, task.target):
                    outcome.fail(note)
                    say(f"  {note}")


# Repos' checks side by side in a merge, the second starting only while the PC has MERGE_MIN_FREE_GB free. Measured on
# Nov 19, 2026 (--all, env2): HomeHiro 68 s and StudyHiro 80 s one after another, 92 s side by side; side by side they
# took 10.5 GB at their peak (alone 6 and 8 GB). 6 GB, not 12: with env0's servers up and other environments busy the
# PC rarely had 12 GB free, so every merge ran its apps one after another; 6 GB covers one app check (Nov 26, a trial).
MERGE_CHECKS = 2
MERGE_MIN_FREE_GB = 6
MERGE_POLL = 2  # seconds between looks for a free slot


def runs_alone(env: int, repo: str) -> bool:
    """A repo whose check names lanes that must run alone (CHECK_SOLO_LANES: the core's tests, whose onnxruntime sends
    a phantom Ctrl-C to the whole console that kills a Node check beside them) runs alone in a merge too."""
    return "CHECK_SOLO_LANES" in (repo_dir(env, repo) / "scripts" / "check.sh").read_text(encoding="utf-8")


def free_gb() -> float:
    """The PC's free memory in GB (what can be used without paging); unknown: plenty."""
    if os.name == "nt":
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                        *[(n, ctypes.c_ulonglong) for n in ("total", "avail", "total_page", "avail_page",
                                                             "total_virtual", "avail_virtual", "avail_extended")]]

        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return status.avail / 1024 ** 3
        return float("inf")
    with contextlib.suppress(OSError, ValueError, StopIteration):
        with open("/proc/meminfo", encoding="utf-8") as f:
            return int(next(x for x in f if x.startswith("MemAvailable:")).split()[1]) / 1024 ** 2
    return float("inf")


def check_repo(task: Task, env: int, repo: str, failed: list[str]) -> None:
    """One repo's check.sh as a step of the merge, its output in a log; a failure is added to ``failed``. An app beside
    a changed kit: its parts name the core files they read (@hiroleague:...), so the check runs exactly the parts the
    kit change reaches."""
    log = LOGS / "check" / f"{task.id}-{repo}.log"
    with step(task.id, env, "check", repo, log=log) as outcome:
        out = subprocess.run([bash(), "-lc", "./scripts/check.sh"], cwd=repo_dir(env, repo),
                             capture_output=True, text=True, encoding="utf-8", errors="replace")
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(out.stdout + out.stderr, encoding="utf-8")
        if out.returncode != 0:
            failed.append(f"{repo} (log: {log})")
            outcome.fail(f"check.sh failed (log: {log})")


def check_repos(task: Task, env: int, repos: list[str]) -> list[str]:
    """The merge's checks; returns the failed ones. A repo that must run alone (the core) runs first, by itself; the
    others two at a time, the second starting only while MERGE_MIN_FREE_GB are free (each check already runs two lanes
    and uses every core). Why: a kit change checks every app, and one after another that took 13 merges 93 min."""
    failed: list[str] = []
    alone = [r for r in repos if runs_alone(env, r)]
    for repo in alone:
        check_repo(task, env, repo, failed)
    with ThreadPoolExecutor(MERGE_CHECKS) as pool:
        started = []
        for repo in (r for r in repos if r not in alone):
            while running := [f for f in started if not f.done()]:
                if len(running) < MERGE_CHECKS and free_gb() >= MERGE_MIN_FREE_GB:
                    break
                time.sleep(MERGE_POLL)
            # In a copy of this context: the check is a step inside the merge
            started.append(pool.submit(contextvars.copy_context().run, check_repo, task, env, repo, failed))
        for f in started:
            f.result()  # a check that raised (not failed: raised) raises here
    return failed


def waiting_installs_note(waiting: dict[str, list[str]]) -> str:
    """What to tell Michel when merge left env0 installs waiting."""
    lines = ["env0's packages changed under servers that are running, so their install waits:"]
    for repo, held in waiting.items():
        names = " ".join(held)
        lines.append(f"  {repo}: hiro-work down 0 {names}, then hiro-work install 0 {repo}, then hiro-work up 0 {names}")
    return "\n".join(lines)


def cmd_install(a) -> None:
    """Install packages in an environment where a lock file changed (none named: every repo), servers down."""
    repos = a.repos or REPOS
    unknown = [r for r in repos if r not in REPOS]
    if unknown:
        raise Stop(f"No repo {', '.join(unknown)}. Repos: {', '.join(REPOS)}.")
    held = sorted({n for r in repos for n in install(a.env, r, None, spare_servers=True)})
    if held:  # the rest is installed; a server that runs on the others' packages must stop first
        raise Stop(f"env{a.env}'s {', '.join(held)} runs on packages that changed: hiro-work down {a.env} "
                   f"{' '.join(held)}, then install again.")
    say(f"env{a.env}'s packages are installed.")


def open_ids(*states: str) -> set[str]:
    """The ids of the open tasks in these states."""
    return {t.id for t in load_tasks() if t.state in states}


def follow_plans(task_id: str, to: str, when: tuple[str, ...], others: set[str]) -> None:
    """CodeHiro's copy of each plan naming the task follows what happened to it (plan.follow), then says so: the plan
    doc's states catch up when the plan ends (plans.md), since CodeHiro holds where a plan stands."""
    import plan

    for line in plan.follow(task_id, to, when, others - {task_id}):
        say(line)


def can_cancel(task: Task) -> None:
    """Stop before anything moves: a working task's uncommitted files would be lost."""
    if task.state not in ("working", "paused"):
        raise Stop(f"Task {task.id} isn't open: only a working or paused task can be cancelled.")
    for repo in task.repos if task.env else []:
        if dirty(repo_dir(task.env, repo)):
            raise Stop(f"env{task.env}'s {repo} has uncommitted files: commit them on {task.branch} (they are kept "
                       f"with it) or discard them, then cancel again.")


def cancel_task(task: Task) -> None:
    """End an open task without merging it: its servers stop, its environment is free, and each repo's branch with
    commits of its own is kept as cancelled/<task> (one with none is removed: nothing to keep). Its record moves to
    tasks/done as cancelled; hiro-work reopen takes it back."""
    can_cancel(task)
    env = task.env
    if env:
        with step(task.id, env, "servers down"):
            servers_down(env)
    kept = []
    for repo in task.repos:
        d = repo_dir(env or 0, repo)
        if env:
            git(d, "switch", "-q", "--detach", main_of(repo))
        if not git(d, "rev-parse", "--verify", "-q", task.branch, check=False):
            continue
        # Its own commits: those its plan's branch lacks, for a task on one (the plan's commits aren't its own)
        if git(d, "rev-list", "--count", f"{follow_ref(task, repo)}..{task.branch}") == "0":
            git(d, "branch", "-q", "-D", task.branch)
        else:
            # -M: a task cancelled before, reopened and cancelled again replaces its older copy (an ancestor of this one)
            git(d, "branch", "-q", "-M", task.branch, cancelled_branch(task.id))
            kept.append(repo)
    if env:
        release_others(env, task)
    with locked():
        task.state, task.env = "cancelled", None
        save(task)
    event(task=task.id, env=env, step="task", phase="end", ok=True, merged=False, cancelled=True)
    where = f"; env{env} is free" if env else ""
    work = (f"its work is kept on {cancelled_branch(task.id)} in {', '.join(kept)}" if kept
            else "it had no commits of its own")
    say(f"Task {task.id} cancelled{where}: {work}. hiro-work reopen {task.id} takes it back.")


def cmd_cancel(a) -> None:
    """A task given up: it ends unmerged. A plan phase it worked on goes back to Next (no other open task works on it):
    the plan goes on."""
    task = get(a.task)
    cancel_task(task)
    follow_plans(task.id, "next", ("working", "review", "paused"), open_ids("working", "paused"))


def cmd_reopen(a) -> None:
    """A cancelled task taken back: its branches come back from cancelled/<task> (or start again from main where it had
    no commits), then it resumes in a free environment. A merged task can't be reopened: start a new one."""
    done = TASKS / "done" / f"{a.task}.json"
    if task_path(a.task).exists():
        raise Stop(f"Task {a.task} is open already.")
    if not done.exists():
        raise Stop(f"No task '{a.task}' has ended.")
    task = task_from(json.loads(done.read_text(encoding="utf-8")))
    if task.state != "cancelled":
        raise Stop(f"Task {task.id} was merged: it can't be reopened. Start a new task for more work.")
    if task.target:
        import plan

        p = plan.latest(task.plan)
        if p and not plan.is_open(p):
            raise Stop(f"Plan {task.plan} is closed, and {task.id} worked on its branch: open the plan again first (a "
                       "send with a phase still to do), then reopen the task.")
    for repo in task.repos:
        d = repo_dir(0, repo)
        if git(d, "rev-parse", "--verify", "-q", cancelled_branch(task.id), check=False):
            git(d, "branch", "-q", "-m", cancelled_branch(task.id), task.branch)
        elif not git(d, "rev-parse", "--verify", "-q", task.branch, check=False):
            git(d, "branch", "-q", task.branch, follow_ref(task, repo))  # its plan's branch, for a task on one
    with locked():
        task.state, task.env = "paused", None
        save(task)
        done.unlink(missing_ok=True)
    event(task=task.id, env=None, step="reopened", phase="end", ok=True)
    follow_plans(task.id, "working", ("next",), set())
    cmd_resume(argparse.Namespace(task=task.id, env=a.env, part_of=None))


def cmd_pause(a) -> None:
    task = get(a.task)
    if not task.env:
        raise Stop(f"Task {task.id} is paused already.")
    env = task.env
    for repo in task.repos:
        d = repo_dir(env, repo)
        if dirty(d):
            git(d, "add", "-A")
            git(d, "commit", "-q", "--no-verify", "-m", f"WIP (paused) {task.id}")
        git(d, "switch", "-q", "--detach", main_of(repo))
    release_others(env, task)
    with step(task.id, env, "servers down"):
        servers_down(env)
    with locked():
        task.state, task.env = "paused", None
        save(task)
    event(task=task.id, env=env, step="paused", phase="end", ok=True)
    say(f"Task {task.id} paused on {task.branch}; env{env} is free.")
    follow_plans(task.id, "paused", ("working", "review"), open_ids("working"))


def cmd_resume(a) -> None:
    with locked():
        tasks = load_tasks()
        task = get(a.task)
        if task.state != "paused":
            raise Stop(f"Task {task.id} isn't paused.")
        busy = {t.env for t in tasks if t.state == "working"}
        env = a.env or next((e for e in ENVS if e and e not in busy), None)
        if env is None:
            raise Stop("Every environment is busy.")
        task.state, task.env = "working", env
        save(task)
    init_env(env, task.id)
    for repo in REPOS:
        d = repo_dir(env, repo)
        if repo in task.repos:
            git(d, "switch", "-q", task.branch)
            if git(d, "log", "-1", "--format=%s").startswith("WIP (paused)"):
                git(d, "reset", "-q", "--soft", "HEAD~1")
                git(d, "reset", "-q")
        else:
            git(d, "switch", "-q", "--detach", follow_ref(task, repo))
    install_all(env, REPOS, task.id)
    refresh_data(env, task.id, task.data)
    if a.part_of is not None:
        with locked():
            task.part_of = part_of_name(a.part_of)
            save(task)
    event(task=task.id, env=env, step="resumed", phase="end", ok=True,
          **({"part_of": task.part_of} if a.part_of is not None else {}))
    follow_plans(task.id, "working", ("paused",), set())
    card(task)


# ------------------------------------------------------------------------------------------------------- servers
# Every server runs in a Windows Terminal window of its own environment ("hiro-envN"), one tab each, outside Claude:
# closing Claude leaves them running. Each tab's output also goes to C:\hiro\logs\envN\<server>.log.

RUN = ROOT / "run"


@dataclass
class Server:
    name: str
    cwd: Path
    command: str
    port: int
    env: dict[str, str] = field(default_factory=dict)
    env_file: Path | None = None  # KEY=value lines loaded first (an app's .env.dev)


def servers(env: int) -> dict[str, Server]:
    """What each server is, in one environment (ports from its block; the shared dev.ps1 isn't used: it takes its
    ports from the committed app.env and stops whatever listens on them)."""
    p, here = ports(env), env_dir(env)
    core = here / "hiroleague"
    out = {
        "core": Server("core", core / "hiroserver", f"uv run hiro start -W {workspace_name(env)} --admin -f",
                       p["core-admin"], {"HIRO_ADMIN_UI_EXTERNAL": "1", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}),
        "core-ui": Server("core-ui", core / "admin_frontend", f"npm.cmd run dev -- --port {p['core-ui']} --strictPort",
                          p["core-ui"], {"HIRO_ADMIN_ORIGIN": f"http://127.0.0.1:{p['core-admin']}"}),
        # The device web app (device chat's Flutter app), only when named: `up <env> device-web`. It pairs with the
        # environment's own gateway (ws://127.0.0.1:7N17, the address the admin's pairing code gives). Its generated
        # code (freezed, riverpod, drift) is out of git, so the code generator runs first (quick once it has run).
        "device-web": Server("device-web", core / "device_apps",
                             "flutter.bat pub get && dart.bat run build_runner build --delete-conflicting-outputs && "
                             f"flutter.bat run -d web-server --web-hostname 127.0.0.1 --web-port {p['device-web']} "
                             "--dart-define=HIRO_ENV=dev", p["device-web"]),
    }
    if env:  # the provider keys in the PC's environment, blanked unless the task asks for AI (data.py)
        out["core"].env[switches.ENV] = str(data_dir(env) / switches.FILE)
        out["core"].env.update(data.core_env(dict(os.environ), real_of(env), copy_lists(),
                                             data.read_store(sys.modules[__name__])))
    for a in appfile.APPS:  # each app as apps.toml says
        api, ui, repo = p[f"{a.repo}-api"], p[f"{a.repo}-ui"], here / a.repo
        fill = {"port": str(api), "data": str(app_data(env, a)), "repo": "{repo}"}  # {repo} stays for the app
        out[f"{a.repo}-api"] = Server(
            f"{a.repo}-api", repo / a.backend, a.api.format(**fill), api,
            # PORT: the kit claims the app's name on the port it really runs on here (hiroleague.listen_port), not its
            # live one, which made an environment's name answer 502
            {"PYTHONUTF8": "1", "PORT": str(api), **{k: v.format(**fill) for k, v in a.api_env.items()}},
            repo / ".env.dev")
        # --host: 127.0.0.1 only, as every app (Vite's default "localhost" is IPv6-only on this PC)
        out[f"{a.repo}-ui"] = Server(f"{a.repo}-ui", repo / a.frontend,
                                     f"npm.cmd run dev -- --port {ui} --strictPort --host 127.0.0.1", ui,
                                     {a.ui_api_env: f"http://127.0.0.1:{api}"})
    return out


def pick_servers(env: int, names: list[str]) -> list[Server]:
    """Names: a server ("homehiro-ui"), an app or "core" (both of its servers). None given: the core and the apps
    the environment's task reserves, or the core and every app when it has no task."""
    every = servers(env)
    if not names:
        held = [t for t in load_tasks() if t.state == "working" and t.env == env]
        apps = sorted({r for t in held for r in t.repos if r in SERVED}) if held and env else SERVED
        names = ["core", *apps]
    chosen: list[Server] = []
    for n in names:
        if n in PORT_ALIASES:  # one of the core's own ports: the core's server alone
            group = [every[PORT_ALIASES[n]]]
        else:
            group = [s for k, s in every.items() if k == n or k.startswith(n + "-")]
        if not group:
            raise Stop(f"No server '{n}'. Servers: {', '.join(every)} (or an app's name for both of its servers; "
                       f"{', '.join(PORT_ALIASES)} start the core).")
        chosen += [s for s in group if s not in chosen]
    return chosen


def runner(env: int, s: Server) -> Path:
    """A small PowerShell script per server: its folder, its settings (the app's .env.dev read at start, as
    dev.ps1 does, so no setting is copied here), its PID, and its output both on screen and in its log."""
    log = LOGS / f"env{env}" / f"{s.name}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    pid = RUN / f"env{env}" / f"{s.name}.pid"
    pid.parent.mkdir(parents=True, exist_ok=True)
    q = lambda v: "'" + str(v).replace("'", "''") + "'"  # noqa: E731 - a PowerShell single-quoted string
    lines = [
        f"$host.UI.RawUI.WindowTitle = {q(f'env{env} {s.name}')}",
        f"Set-Location {q(s.cwd)}",
    ]
    if s.env_file:
        lines += [
            f"if (Test-Path {q(s.env_file)}) {{ foreach ($l in Get-Content {q(s.env_file)}) {{",
            "  if ($l -match '^\\s*([A-Za-z_][A-Za-z0-9_]*)\\s*=\\s*(.*?)\\s*$') { Set-Item \"env:$($Matches[1])\" $Matches[2] } } }",
        ]
    lines += [f"$env:{k} = {q(v)}" for k, v in s.env.items()]
    lines += [
        f"Set-Content -Path {q(pid)} -Value $PID",
        f"\"== env{env} {s.name} on port {s.port}, started $(Get-Date)\" | Out-File -FilePath {q(log)} -Encoding utf8",
        f"cmd /c {q(s.command + ' 2>&1')} | ForEach-Object {{ $_; $_ | Out-File -FilePath {q(log)} -Append "
        "-Encoding utf8 }",
        f"\"== stopped $(Get-Date)\" | Out-File -FilePath {q(log)} -Append -Encoding utf8",
    ]
    path = RUN / f"env{env}" / f"{s.name}.ps1"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
    return path


def listening(port: int) -> bool:
    import socket
    with contextlib.suppress(OSError), socket.create_connection(("127.0.0.1", port), timeout=0.2):
        return True
    return False


def open_tabs(env: int, chosen: list[Server]) -> None:
    """Each server in a tab of the environment's own Windows Terminal window (hiro-envN), outside Claude."""
    if not chosen:
        return
    wt = [shutil.which("wt.exe") or "wt.exe", "-w", f"hiro-env{env}"]
    for i, s in enumerate(chosen):
        if i:
            wt.append(";")
        wt += ["new-tab", "--title", f"env{env} {s.name}", "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
               "-File", str(runner(env, s))]
    subprocess.Popen(wt, creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))


def core_workspace(env: int) -> Path:
    return data_dir(env) / "core" / "default"


def paired(env: int, a: appfile.App) -> bool:
    """Whether the app's key (its data folder's hiroleague/) is one this environment's core knows."""
    identity = app_data(env, a) / "hiroleague" / "extension_identity.json"
    db = core_workspace(env) / "db" / "workspace.db"
    try:
        ext_id = json.loads(identity.read_text(encoding="utf-8")).get("extension_id")
    except (OSError, ValueError):
        return False
    if not ext_id or not db.exists():
        return False
    con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
        # extension_records, the one extension manager's list (the old "extensions" table stays as it was copied)
        return con.execute("select 1 from extension_records where extension_id = ?", (ext_id,)).fetchone() is not None
    finally:
        con.close()


def pair_apps(env: int, apps: list[appfile.App]) -> None:
    """Pair apps with the environment's running core (pair_apps.py, in the core's own environment), one at a time."""
    url = f"ws://127.0.0.1:{ports(env)['core-socket']}"
    args = [f"{x.name}={app_data(env, x) / 'hiroleague'}" for x in apps]
    out = subprocess.run(["uv", "run", "python", str(Path(__file__).with_name("pair_apps.py")),
                          str(core_workspace(env)), url, *args],
                         cwd=repo_dir(env, "hiroleague") / "hiroserver", capture_output=True, text=True,
                         # its lines may hold the core's words ("Settings → HiroLeague"): piped, cp1252 can't write them
                         encoding="utf-8", errors="replace", env={**os.environ, "PYTHONIOENCODING": "utf-8:replace"})
    for line in (out.stdout or "").splitlines():
        say(f"  pairing: {line}")
    if out.returncode:
        say(f"  pairing didn't finish: {(out.stderr or '').strip().splitlines()[-1:] or 'see above'}")


def cmd_up(a) -> None:
    env = a.env
    if env and not (env_dir(env) / "hiroleague" / ".git").exists():
        raise Stop(f"env{env} isn't made yet (hiro-work init {env}).")
    chosen = [s for s in pick_servers(env, a.servers) if not listening(s.port)]
    if not chosen:
        say("Already running.")
        return
    starting = {s.name for s in chosen}
    configure_apps(env, [x for x in appfile.APPS if f"{x.repo}-api" in starting])
    # An app with no database yet (a vanilla environment, its first start) can't be pointed at the core before it
    # starts: it reads the core's address once, at start (the kit's link). It starts, makes its database, gets the
    # addresses, and starts again (first_start)
    fresh = [x for x in appfile.APPS if f"{x.repo}-api" in starting and not (app_data(env, x) / x.settings_db).exists()]
    # An app starting without a key this core knows is paired first, while it isn't running: the core starts (or
    # runs) first, then each such app pairs (pair_apps.py), then the apps start and connect with their keys
    unpaired = [x for x in appfile.APPS if f"{x.repo}-api" in starting and not paired(env, x)]
    deadline = time.monotonic() + a.wait
    with step(None, env, "servers up", servers=sorted(starting), known=list(servers(env))):
        if unpaired:
            core_first = [s for s in chosen if s.name in ("core", "core-ui")]
            open_tabs(env, core_first)
            socket = ports(env)["core-socket"]
            while not listening(socket) and time.monotonic() < deadline:
                time.sleep(1)
            if listening(socket):
                pair_apps(env, unpaired)
            else:
                say(f"  The core isn't running on {socket}, so {', '.join(x.title for x in unpaired)} can't pair: "
                    f"start it too (`hiro-work up {env} core`).")
            open_tabs(env, [s for s in chosen if s not in core_first])
            deadline = max(deadline, time.monotonic() + a.wait)  # the apps get their own wait after the core's
        else:
            open_tabs(env, chosen)
        waiting = list(chosen)
        while waiting and time.monotonic() < deadline:
            time.sleep(1)
            waiting = [s for s in waiting if not listening(s.port)]
    if fresh and not waiting:
        first_start(env, fresh, a.wait)
    for s in chosen:
        mark = "up  " if s not in waiting else "NOT UP"
        say(f"  {mark} {s.name:16} http://127.0.0.1:{s.port}   log: {LOGS / f'env{env}' / f'{s.name}.log'}")
    if waiting:
        raise Stop("Some servers didn't answer in time: read their logs (or their tabs in the hiro-env window).")


def first_start(env: int, apps: list[appfile.App], wait: int) -> None:
    """Apps that just made their database at their first start: once it has its settings table, point them at this
    environment (configure_apps) and start their APIs again, so they connect to its core."""
    deadline = time.monotonic() + wait
    ready: list[appfile.App] = []
    with step(None, env, "first start", servers=[f"{x.repo}-api" for x in apps]):
        for x in apps:
            db = app_data(env, x) / x.settings_db
            while time.monotonic() < deadline:
                if db.exists():
                    with contextlib.suppress(sqlite3.Error), contextlib.closing(sqlite3.connect(db)) as con:
                        if con.execute("select 1 from sqlite_master where name = 'setting'").fetchone():
                            ready.append(x)
                            break
                time.sleep(1)
            else:
                say(f"  {x.title} made no database in time: it starts with no core address (hiro-work up again)")
        if not ready:
            return
        configure_apps(env, ready)
        names = [f"{x.repo}-api" for x in ready]
        servers_down(env, names)
        again = [servers(env)[n] for n in names]
        open_tabs(env, again)
        while [s for s in again if not listening(s.port)] and time.monotonic() < deadline + wait:
            time.sleep(1)
        say(f"  started again with this core's address: {', '.join(x.title for x in ready)}")


def pids_listening(port_list: list[int]) -> set[int]:
    out = run(["powershell", "-NoProfile", "-Command",
               "Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | "
               "Where-Object { $_.LocalPort -in @(" + ",".join(map(str, port_list)) + ") } | "
               "ForEach-Object { $_.OwningProcess }"], check=False)
    return {int(x) for x in out.split() if x.strip().isdigit() and int(x) > 4}


def servers_down(env: int, names: list[str] | None = None) -> None:
    """Stop an environment's servers: each runner's process tree, then anything still on their ports (a reloader's
    child). Only this environment's ports are touched."""
    chosen = pick_servers(env, names) if names else list(servers(env).values())
    port_list = [s.port for s in chosen]
    if any(s.name == "core" for s in chosen):  # the core's other listeners, its gateway's too
        port_list += [ports(env)[k] for k in ("core-socket", "core-http", "core-gateway")]
    for s in chosen:
        pid_file = RUN / f"env{env}" / f"{s.name}.pid"
        if pid_file.exists():
            run(["taskkill", "/PID", pid_file.read_text().strip(), "/T", "/F"], check=False)
            pid_file.unlink(missing_ok=True)
    for pid in pids_listening(port_list):
        run(["taskkill", "/PID", str(pid), "/T", "/F"], check=False)


def cmd_down(a) -> None:
    named = [s.name for s in pick_servers(a.env, a.servers)] if a.servers else None  # none named: all of them
    with step(None, a.env, "servers down", known=list(servers(a.env)), **({"servers": named} if named else {})):
        servers_down(a.env, a.servers)
    up = [n for n, s in servers(a.env).items() if listening(s.port)]
    say("Still up: " + ", ".join(up) if up else f"env{a.env}'s servers are down.")


def bash() -> str:
    return r"C:\Program Files\Git\bin\bash.exe"


# ----------------------------------------------------------------------------------------------------- reports


def cmd_status(a) -> None:
    tasks = load_tasks()
    say("Environments:")
    for env in ENVS:
        here = [t for t in tasks if t.env == env and t.state == "working"]
        up = [n for n, p in ports(env).items() if listening(p)]
        what = "; ".join((f"{t.part_of} › " if t.part_of else "") + f"{t.id} ({', '.join(t.repos)}"
                         + (f", into {t.target})" if t.target else ")") for t in here)             or ("main, Michel's dev" if env == 0 else "free")
        exists = env == 0 or (env_dir(env) / "hiroleague" / ".git").exists()
        say(f"  env{env}  {'' if exists else '(not made yet) '}{what}" + (f"  | up: {', '.join(up)}" if up else ""))
    paused = [t for t in tasks if t.state == "paused"]
    if paused:
        say("Paused: " + ", ".join(f"{t.id} ({t.updated[:10]})" for t in paused))


def merged_left(listing: str, main: str, keep: tuple[str, ...] = ()) -> list[str]:
    """The merged branches left behind, from `git branch --merged`: not the main branch, not an open plan's branch
    (``keep``: it may hold nothing yet), and not one checked out here ("*") or in another worktree ("+", an open task's
    branch in env1..env5: it is in use, not left)."""
    out = []
    for line in listing.splitlines():
        if line[:1] in ("*", "+"):
            continue
        b = line.strip()
        if b and b not in (main, "main", "dev", *keep) and not b.startswith("("):
            out.append(b)
    return out


def win_path(p: Path | str) -> str:
    """A path as the sweep compares it: Windows slashes, lower case.

    A fix: git lists worktrees with forward slashes, which the sweep turns into Windows ones; a path it compared without
    the same change made env0 and the docs desk look like stray worktrees on Linux (Simone's deploy check)."""
    return str(p).replace("/", "\\").lower()


def cmd_sweep(a) -> None:
    say("Left behind (nothing is removed here):")
    findings: list[dict] = []

    def found(kind: str, repo: str, what: str, fix: str) -> None:
        say(f"  {repo}: {what}")
        findings.append({"kind": kind, "where": repo, "what": what, "since": None, "fix": fix})

    import docs
    import plan

    open_plans = plan.whole_branches()
    desk = win_path(docs.DESK)  # the docs desk is hiro-docs' one worktree outside the environments
    for repo in REPOS:
        d = repo_dir(0, repo)
        for block in git(d, "worktree", "list", "--porcelain").split("\n\n"):
            path = block.splitlines()[0].removeprefix("worktree ").replace("/", "\\")
            on = next((x.removeprefix("branch refs/heads/") for x in block.splitlines() if x.startswith(
                "branch refs/heads/plan/")), "")
            if on:  # a plan's branch is never checked out: a merge into it refuses while one is
                found("plan", repo, f"{path} has {on} checked out", f"git -C {path} switch --detach {on}")
            if path.lower() in (win_path(d), desk) or path.lower().startswith(win_path(ROOT) + "\\env"):
                continue
            found("worktree", repo, f"worktree outside C:\\hiro\\env1-5: {path}", f"git -C {d} worktree remove {path}")
        for b in git(d, "for-each-ref", "--format=%(refname:short)", "refs/heads/plan/").split():
            if b not in open_plans:  # its plan closed, landed, was renamed, or never sent as shipping whole
                found("plan", repo, f"{b}: no open plan ships whole on it", f"hiro-work plan list; git -C {d} branch -D {b}")
        main = main_of(repo)
        merged = merged_left(git(d, "branch", "--merged", main), main, tuple(open_plans))
        if merged:
            found("merged", repo, f"{len(merged)} merged branch(es) kept: {', '.join(merged)}",
                  f"git -C {d} branch -d {' '.join(merged)}")
        branch = git(d, "branch", "--show-current")
        if branch != main:
            found("off-main", repo, f"env0 checkout is on '{branch}', not {main}", f"git -C {d} switch {main}")
    if not findings:
        say("  nothing")
    # CodeHiro's Sweep shows the last report, beside the paused tasks and the servers left up it works out itself
    event(task=None, env=None, step="sweep", phase="end", ok=True, findings=findings)


def cmd_describe(a) -> None:
    """What an open task does, or what bigger work it is a piece of, changed ("" clears it); the Work area follows."""
    if a.about is None and a.part_of is None:
        raise Stop("Say what changes: --about and/or --part-of.")
    with locked():
        task = get(a.task)
        changed: dict[str, str] = {}
        if a.about is not None:
            task.about = changed["about"] = a.about.strip()
        if a.part_of is not None:
            task.part_of = changed["part_of"] = part_of_name(a.part_of)
        save(task)
    event(task=task.id, env=task.env, step="describe", phase="end", ok=True, **changed)
    say(f"Task {task.id}: " + "; ".join(f"{k.replace('_', ' ')} {v or '(none)'}" for k, v in changed.items()))


def cmd_review(a) -> None:
    """The task's work waits for Michel's review: CodeHiro shows it so until the task's next step."""
    task = get(a.task)
    if task.state != "working":
        raise Stop(f"Task {task.id} isn't working (it is {task.state}).")
    event(task=task.id, env=task.env, step="review", phase="start")
    say(f"Task {task.id} waits for your review (CodeHiro's Work page says so until its next step).")
    follow_plans(task.id, "review", ("working",), open_ids("working", "paused"))


# ---------------------------------------------------------------------------------------------------------- main

# Commands that run checks or deploys for minutes in a console
LONG_COMMANDS = ("merge", "deploy")


def ignore_console_interrupt() -> None:
    """A fix: onnxruntime, loaded by the core's tests, sends a phantom Ctrl-C to every process on the console. It killed
    a merge inside ``subprocess.run(check.sh)`` (KeyboardInterrupt), though check-engine.sh and run-tests.sh already
    ignore it. A merge or a deploy is stopped with Ctrl-Break, ``hiro-work deploy --stop`` or by closing the tab, as
    scripts/run-tests.sh says."""
    signal.signal(signal.SIGINT, signal.SIG_IGN)


def main(argv: list[str] | None = None) -> int:
    utf8_output()
    p = argparse.ArgumentParser(prog="hiro-work", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("task")
    s.add_argument("--repos", required=True)
    s.add_argument("--kit", action="store_true", help="a kit, SDK or build-kit change: also reserves the apps")
    s.add_argument("--title")
    s.add_argument("--env", type=int, choices=list(ENVS))
    s.add_argument("--part-of", help="the bigger work it is a piece of: a name, or a task's id (its title is used)")
    s.add_argument("--phase", help="with --part-of a plan: the phase it works on, as the plan names it (it joins the "
                   "phase's tasks in CodeHiro, and each station moves the phase from then on)")
    s.add_argument("--own-branch", action="store_true",
                   help="a phase of open work: a task of its own beside its open tasks (a step joins that task)")
    s.add_argument("--on-main", action="store_true",
                   help="a piece of a plan that ships whole that must ship now: it goes to main, not the plan's branch")
    s.add_argument("--about", help="what it does, in a sentence (the Work area shows it under its name)")
    s.add_argument("--preset", default=switches.DEFAULT,
                   help="env1..5: its switchboard's preset (hiro-work preset list); Safe when not said")
    s.add_argument("--set", action="append", metavar="SYSTEM=MODE", help="one system changed from the preset: ai=real")
    s.add_argument("--quick-sign-in", action="store_true",
                   help="env1..5, for interactive use: no sign-in screen, everyone is the owner")
    s.add_argument("--as", dest="as_person", metavar="PERSON",
                   help="env1..5, for interactive use: no sign-in screen, everyone is this person of the family list")
    s.add_argument("--data", default="env0", metavar="SOURCE",
                   help="where its data comes from: env0 (default), vanilla (a fresh install), live or live:<stamp>")
    for verb in ("pause", "review"):
        sub.add_parser(verb).add_argument("task")
    sub.add_parser("sync", help="bring the latest dev/main into the task's branches, without merging the task").add_argument(
        "task")
    sub.add_parser("merge", help="bring the latest in, check, fast-forward env0, release the environment").add_argument("task")
    cl = sub.add_parser("reserve", help="add repos to an open task (free in its environment)")
    cl.add_argument("task")
    cl.add_argument("repos", help="comma-separated")
    cl.add_argument("--kit", action="store_true", help="a kit change: the apps that read it too")
    fr = sub.add_parser("fresh", help="the commit hook's check: the commit's task, overlaps, the other repos")
    fr.add_argument("path", help="a folder inside the repo being committed")
    ds = sub.add_parser("describe", help="change what an open task does (--about) or what it is part of (--part-of)")
    ds.add_argument("task")
    ds.add_argument("--about", help="what it does, in a sentence; \"\" clears it")
    ds.add_argument("--part-of", help="the bigger work it is a piece of; \"\" makes it a task of its own")
    cn = sub.add_parser("cancel", help="end an open task unmerged; its work is kept on cancelled/<task>")
    cn.add_argument("task")
    ro = sub.add_parser("reopen", help="take a cancelled task back, in a free environment")
    ro.add_argument("task")
    ro.add_argument("--env", type=int, choices=[e for e in ENVS if e])
    r = sub.add_parser("resume")
    r.add_argument("task")
    r.add_argument("--env", type=int, choices=[e for e in ENVS if e])
    r.add_argument("--part-of", help="the bigger work it is a piece of (sets it)")
    i = sub.add_parser("init")
    i.add_argument("env", type=int, choices=[e for e in ENVS if e])
    u = sub.add_parser("up", help="start servers (none named: the core and the task's apps)")
    u.add_argument("env", type=int, choices=list(ENVS))
    u.add_argument("servers", nargs="*")
    u.add_argument("--wait", type=int, default=90, help="seconds to wait for them to answer")
    d = sub.add_parser("down", help="stop servers (none named: all of the environment's)")
    d.add_argument("env", type=int, choices=list(ENVS))
    d.add_argument("servers", nargs="*")
    c = sub.add_parser("configure", help="point an environment's core and apps at its own ports")
    c.add_argument("env", type=int, choices=list(ENVS))
    c.add_argument("--data", action="store_true",
                   help="env1..5 with no task: copy env0's data again first (servers down)")
    ins = sub.add_parser("install", help="install packages where a lock file changed (none named: every repo)")
    ins.add_argument("env", type=int, choices=list(ENVS))
    ins.add_argument("repos", nargs="*")
    sub.add_parser("status")
    sub.add_parser("sweep")
    sw = sub.add_parser("switch", help="env1..5: what it reaches of each outside system (its servers down to change)")
    sw.add_argument("env", type=int, choices=list(ENVS))
    sw.add_argument("--preset", help="a preset's name (hiro-work preset list)")
    sw.add_argument("--set", action="append", metavar="SYSTEM=MODE", help="one system's mode, like ai=real (repeat)")
    sw.add_argument("--sign-in", choices=["on", "off"], help="on: as live; off: no sign-in screen, everyone is the owner")
    sw.add_argument("--as", dest="as_person", metavar="PERSON",
                    help="no sign-in screen: everyone is this person of its family list (a name or an id)")
    sw.add_argument("--restart", action="store_true", help="stop its servers that are up, and start them again after")
    sw.set_defaults(func=cmd_switch)
    pr = sub.add_parser("preset", help="the switchboard's presets: list, save <name> --from <env>, remove <name>")
    pr.add_argument("what", choices=["list", "save", "remove"])
    pr.add_argument("name", nargs="?", default="")
    pr.add_argument("--from", dest="from_env", type=int, choices=[1, 2, 3, 4, 5])
    pr.add_argument("--preset", help="save: the preset it starts from")
    pr.add_argument("--set", action="append", metavar="SYSTEM=MODE", help="save: a system changed from --preset")
    pr.add_argument("--about", help="what it is for, in a few words")
    pr.set_defaults(func=cmd_preset)
    rd = sub.add_parser("refresh-data", help="live -> env0: fetch a scrubbed live copy; --apply puts it in env0")
    rd.add_argument("--apply", metavar="STAMP", help="a copy in C:\\hiro\\data\\live-copies, or 'latest'")
    rd.add_argument("--now", action="store_true", help="fetch a new copy and put it in env0, in one go")
    rd.add_argument("--files", action="store_true",
                    help="only the folders the copy lists fetch (the uploads the databases point at)")
    rd.set_defaults(func=lambda a: data.cmd_refresh_data(a, sys.modules[__name__]))
    sc = sub.add_parser("secret", help="the PC's dev secrets, by name: list, fill (from env0 and the PC), set <name>")
    sc.add_argument("what", choices=["list", "fill", "set"])
    sc.add_argument("name", nargs="?", default="")
    sc.set_defaults(func=lambda a: data.cmd_secret(a, sys.modules[__name__]))
    dt = sub.add_parser("data", help="env1..5: its data again from env0, vanilla or a live copy (servers down)")
    dt.add_argument("env", type=int, choices=list(ENVS))
    dt.add_argument("source", help="env0, vanilla, live (the latest copy, fetched again when an hour old) or live:<stamp>")
    dt.set_defaults(func=cmd_data)
    cl = sub.add_parser("copy-list", help="every repo's copy list (data.toml): what a copy holds, and how")
    cl.add_argument("--check", action="store_true", help="also name what env0's and live's data folders hold that no "
                    "list covers")
    cl.set_defaults(func=lambda a: data.cmd_copy_list(a, sys.modules[__name__]))
    # The deploy lives in deploy.py, which imports this module: run as a script, this is __main__, so it is
    # named hiro_work too, or deploy.py would load a second copy (and its Stop wouldn't be caught here)
    sys.modules.setdefault("hiro_work", sys.modules[__name__])
    import deploy
    deploy.add_parser(sub)
    import audit
    audit.add_parser(sub)
    import plan
    plan.add_parser(sub)
    import docs
    docs.add_parser(sub)
    a = p.parse_args(argv)
    if a.cmd in LONG_COMMANDS:
        ignore_console_interrupt()
    try:
        if getattr(a, "func", None):
            return a.func(a) or 0
        {"start": cmd_start, "sync": cmd_sync, "merge": cmd_merge, "pause": cmd_pause,
         "resume": cmd_resume, "cancel": cmd_cancel, "reopen": cmd_reopen, "status": cmd_status, "sweep": cmd_sweep, "up": cmd_up, "down": cmd_down,
         "review": cmd_review, "describe": cmd_describe, "reserve": cmd_reserve, "fresh": cmd_fresh,
         "configure": cmd_configure, "install": cmd_install, "init": lambda a: init_env(a.env),
         "deploy": deploy.cmd_deploy}[a.cmd](a)
    except Stop as e:
        say(f"\nStopped: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
