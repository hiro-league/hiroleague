r"""hiro-work: the environments every Hiro League task works in (hiro-docs standards/workflow.md).

Every task claims the repos it changes. It works in env0 (Michel's dev: the main checkouts in C:\hiro\env0) while
those repos are free there, else in one of env1..env5: the same repos as git worktrees, kept warm between tasks, each
with its own data (C:\hiro\data\envN) and its own block of ports (7N00-7N49). A task in env0 commits when it finishes;
a task in env1..env5 lands: its branches merge into dev/main and env0 is brought up to them.

    hiro-work status                         environments, tasks, claims, servers
    hiro-work start <task> --repos a,b [--kit] [--title ...] [--about ...] [--part-of ...] [--env N]
    hiro-work describe <task> [--about ...] [--part-of ...]   what it does / what it is part of, changed
    hiro-work move <task>                    env0 -> a free environment, carrying the edits
    hiro-work finish <task>                  env0: every claimed repo committed; release the claims
    hiro-work land <task>                    env1..5: merge, check, update env0, free the environment
    hiro-work park <task> / resume <task>    save the work on its branch and free the environment / take one back
    hiro-work up <env> [server ...] / down <env> [server ...]   servers, in Windows Terminal outside Claude
    hiro-work init <env>                     make (or repair) an environment: worktrees, installs, settings
    hiro-work sweep                          what is left behind (report only)
    hiro-work review <task>                  the task waits for Michel's review (until its next step)
    hiro-work real <task> [--reads] [--ai]   env1..5: which real systems the task's copy reads (data.py)
    hiro-work refresh-data [--apply STAMP] [--files]   live -> env0: a scrubbed live copy, then env0 (data.py)
    hiro-work train [repo ...] [--dry-run]   the deploy train: push and deploy, when Michel says (train.py)

State lives in C:\hiro\tasks (one JSON file per task) and every step is logged to C:\hiro\logs\events.jsonl (with
its time) for CodeHiro's Work area, where ship.py sends it. Standard library only: it runs on the system Python.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import apps as appfile
import data
import ship

ROOT = Path(os.environ.get("HIRO_ROOT", r"C:\hiro"))
TASKS = ROOT / "tasks"
LOGS = ROOT / "logs"
EVENTS = LOGS / "events.jsonl"
ENVS = range(0, 6)

# The repos every environment holds, the core first (it lands first), the apps as apps.toml lists them.
# hiroleague-website lives in env0 only.
REPOS = ["hiroleague", *(a.repo for a in appfile.APPS), "aicam", "hiro-docs"]
MAIN = {"hiroleague": "dev", "hiro-docs": "dev"}  # every other repo's main branch is main
# The apps that read the core's kits, SDK and build kit (../hiroleague): a change there claims them too.
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
PORT_ALIASES = {"core-admin": "core", "core-socket": "core", "core-http": "core", "core-plugin": "core"}
# Core workspace folders an environment never gets: the WhatsApp session (two clients on one account break it),
# the AI tool installs, logs and run files.
CORE_SKIP = {"channels", "plans", "logs", "run"}


def main_of(repo: str) -> str:
    return MAIN.get(repo, "main")


def env_dir(env: int) -> Path:
    return ROOT / f"env{env}"


def repo_dir(env: int, repo: str) -> Path:
    return env_dir(env) / repo


def data_dir(env: int) -> Path:
    return ROOT / "data" / f"env{env}"


def ports(env: int) -> dict[str, int]:
    """The environment's block, 7N00-7N49 (workflow.md, Ports; apps.py). The core listens on four: its admin API, the
    apps' extension socket, its HTTP status API and the channel plugins' socket."""
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


_shipping = False  # this process has started the sender (ship.py) once


def event(**fields) -> None:
    global _shipping
    LOGS.mkdir(parents=True, exist_ok=True)
    fields = {"at": datetime.now().astimezone().isoformat(timespec="seconds"), **fields}
    with open(EVENTS, "a", encoding="utf-8") as f:
        f.write(json.dumps(fields) + "\n")
    # The log is the outbox: the sender posts the new lines to CodeHiro. Only the real log is sent (a test's isn't).
    if not _shipping and EVENTS == ship.EVENTS:
        _shipping = True
        ship.kick()


TAIL_LINES = 100  # a failed step's last lines of log, sent with its end (CodeHiro can't read the PC's files)
TAIL_CHARS = 20_000
_open_steps: list[str] = []  # the steps running now in this process, the innermost last: a new one runs inside it


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


@contextlib.contextmanager
def step(task: str | None, env: int | None, name: str, repo: str | None = None, log: Path | None = None,
         **more):
    """One timed step: printed, and logged as a start and an end event. A step inside another names it as its
    ``parent`` (land's own steps); ``log`` is its log file, whose last lines go with a failed end; ``more`` rides on
    both events (the servers of servers up)."""
    label = f"{name}" + (f" [{repo}]" if repo else "")
    say(f"> {label}")
    where = {"task": task, "env": env, "repo": repo, "step": name}
    if _open_steps:
        where["parent"] = _open_steps[-1]
    event(**where, phase="start", **({"log": str(log)} if log else {}), **more)
    _open_steps.append(name)
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
        _open_steps.pop()
    s = round(time.monotonic() - t, 1)
    if outcome.error:
        event(**where, phase="end", ok=False, seconds=s, error=outcome.error[:300], tail=tail(log), **more)
        say(f"x {label} failed after {s} s")
        return
    event(**where, phase="end", ok=True, seconds=s, **more)
    say(f"  done in {s} s")


COMMITS_MAX = 2000  # one event's commits, at most


def record_commits(task: str, env: int | None, repo: str, frm: str | None, to: str | None, how: str) -> None:
    """The commits a task (or a deploy train) added to a repo, from..to in env0, as a Work event: CodeHiro's Deploys
    shows the tasks whose work each train shipped. ``how``: land, finish (a task in env0), deploy, push."""
    if not frm or not to or frm == to:
        return
    shas = git(repo_dir(0, repo), "rev-list", f"{frm}..{to}", check=False).split()[:COMMITS_MAX]
    if shas:
        event(task=task, env=env, repo=repo, step="commits", phase="end", ok=True, how=how,
              **{"from": frm, "to": to}, commits=shas)


class Stop(Exception):
    """A refusal with a message for the person: nothing half-done is left behind."""


# ------------------------------------------------------------------------------------------------------- commands


def run(args: list[str], cwd: Path | None = None, check: bool = True) -> str:
    out = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and out.returncode != 0:
        raise Stop(f"{' '.join(args[:4])} failed in {cwd}:\n{(out.stderr or out.stdout).strip()[-1500:]}")
    return out.stdout.strip()


def git(repo_path: Path, *args: str, check: bool = True) -> str:
    return run(["git", "-C", str(repo_path), *args], check=check)


def dirty(repo_path: Path) -> list[str]:
    """Uncommitted work: changed, staged or untracked files (.gitignore respected)."""
    return [line for line in git(repo_path, "status", "--porcelain").splitlines() if line.strip()]


# ---------------------------------------------------------------------------------------------------------- state


@dataclass
class Task:
    id: str
    title: str
    env: int | None
    repos: list[str]
    state: str = "working"  # working | parked | done
    base: dict[str, str] = field(default_factory=dict)
    # In env0: what was already uncommitted in each claimed repo when the task started (someone else's): not its own
    before: dict[str, list[str]] = field(default_factory=dict)
    # In env1..env5: the real systems its copy may reach ("reads", "ai"); none by default (data.py)
    real: list[str] = field(default_factory=list)
    # What bigger work it is a piece of ("Work-flow plan"): CodeHiro names it "<part_of> › <title>" and groups by it
    part_of: str = ""
    # What it does, in a sentence: the Work area shows it under its name
    about: str = ""
    created: str = ""
    updated: str = ""

    @property
    def branch(self) -> str:
        return f"task/{self.id}"


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
    if task.state == "done":
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
    """The claimed repos, the core first; a kit change also claims every app that reads the kits."""
    unknown = [r for r in repos if r not in REPOS]
    if unknown:
        raise Stop(f"Unknown repo(s): {', '.join(unknown)}. Repos: {', '.join(REPOS)}.")
    claimed = set(repos) | (set(KIT_READERS) | {"hiroleague"} if kit else set())
    return [r for r in REPOS if r in claimed]


def claims_in(env: int, tasks: list[Task]) -> dict[str, str]:
    """repo -> the task holding it, in one environment."""
    return {r: t.id for t in tasks if t.state == "working" and t.env == env for r in t.repos}


def pick_env(repos: list[str], tasks: list[Task], wanted: int | None) -> int:
    """env0 while its repos are free there, else the first free environment (workflow.md, Claims)."""
    busy = {t.env for t in tasks if t.state == "working" and t.env not in (None, 0)}
    if wanted is not None:
        if wanted == 0:
            held = {r: t for r, t in claims_in(0, tasks).items() if r in repos}
            if held:
                raise Stop("In env0, " + ", ".join(f"{r} is held by {t}" for r, t in held.items()) + ".")
        elif wanted in busy:
            raise Stop(f"env{wanted} is busy.")
        return wanted
    if not any(r in claims_in(0, tasks) for r in repos):
        return 0
    for env in ENVS:
        if env and env not in busy:
            return env
    raise Stop("Every environment is busy: finish, land or park a task first (hiro-work status).")


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


def install(env: int, repo: str, task: str | None = None, force: bool = False) -> None:
    """Install a repo's packages in an environment only when its lock file changed since the last install there."""
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
            with step(task, env, "node install", f"{repo}/{sub}"):
                run(["npm.cmd", "ci", "--prefer-offline", "--no-audit", "--no-fund"], cwd=d)
                stamp.write_text(file_sha(lock))


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


# Sends and HA's automatic writes off; sign-in on, as in env0 (an AUTH line of env0's is dropped), so users and
# roles can be tried in every environment
ENV_DEV_FORCED = {"OUTPUTS": "off", "HA_AUTO_WRITES": "off", "AUTH": None}


def write_env_dev(env: int) -> None:
    """Each app's .env.dev in envN: env0's, with this environment's data folder, no sends or HA's automatic writes,
    sign-in on; real systems as the task asks (data.env_overrides: None drops env0's line)."""
    real = real_of(env)
    for app in APPS:
        src = repo_dir(0, app) / ".env.dev"
        if not src.exists():  # an app with no .env.dev (Code reports) takes its settings from up (apps.toml api_env)
            continue
        lines = src.read_text(encoding="utf-8").splitlines()
        forced = {**ENV_DEV_FORCED, "DATA_DIR": (data_dir(env) / app).as_posix(), **data.env_overrides(app, real)}
        keep = [ln for ln in lines if ln.split("=", 1)[0].strip() not in forced]
        keep += [f"{k}={v}" for k, v in forced.items() if v is not None]
        (repo_dir(env, app) / ".env.dev").write_text("\n".join(keep) + "\n", encoding="utf-8")


def real_of(env: int) -> list[str]:
    """The real systems the task working in envN asked for (data.py); none for env0, which is real already."""
    return next((t.real for t in load_tasks() if t.state == "working" and t.env == env and env), [])


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
        cfg.update(http_port=p["core-http"], plugin_port=p["core-plugin"], admin_port=p["core-admin"],
                   extension_port=p["core-socket"])
        # Left out rather than null: the core's config takes these as text when present (extension_host absent =
        # loopback; no LAN names in env1..env5)
        for key in ("extension_host", *(("site_names_ip", "site_names_caddy_file", "site_names_caddy_reload")
                                        if env else ())):
            if cfg.get(key) is None or env:
                cfg.pop(key, None)
        cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
        configure_apps(env, appfile.APPS)
        if env:
            with sqlite3.connect(ws / "db" / "workspace.db") as con:
                con.execute("update channel_plugins set enabled = 0")
            if workspace_name(env) not in registry_names():
                run(["uv", "run", "hiro", "workspaces", "create", workspace_name(env), "--path", str(ws)],
                    cwd=repo_dir(env, "hiroleague") / "hiroserver")
            # Real systems off unless the task asks (data.py): run on every configure, the copy may be fresh
            for line in data.make_safe(data_dir(env), real_of(env)):
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


def copy_db(src: Path, dst: Path) -> None:
    """A consistent copy of a SQLite database, even while env0's server writes to it (what's in the WAL comes too)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.unlink(missing_ok=True)
    with sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True) as a, sqlite3.connect(dst) as b:
        a.backup(b)


def remove_tree(path: Path) -> None:
    """shutil.rmtree that also removes read-only files: git marks its pack files read-only on Windows, and CodeHiro's
    data holds git mirrors, so a plain rmtree stops on them."""
    def writable_then_retry(func, p, _exc):
        os.chmod(p, 0o666)
        func(p)
    shutil.rmtree(path, onexc=writable_then_retry)


def refresh_data(env: int, task: str | None = None) -> None:
    """envN's data from env0's: the databases copied, the pictures hard-linked, the big folders left out (workflow.md,
    Data and real systems). Removing the old folder first removes only its links: env0's pictures stay."""
    if env == 0:
        return
    for app in APPS:
        src, dst = app_data(0, appfile.BY_REPO[app]), data_dir(env) / app
        with step(task, env, "data copy", app):
            if dst.exists():
                remove_tree(dst)
            dst.mkdir(parents=True)
            for db in src.glob("*.db"):
                copy_db(db, dst / db.name)
            # The app's link to the core: its key and identity (the core copy below knows the same key)
            if (src / "hiroleague").is_dir():
                shutil.copytree(src / "hiroleague", dst / "hiroleague")
            # Pictures the databases point at: hard links to env0's (data.py)
            for line in data.link_pictures(src, dst, app):
                say(f"  {line}")
    with step(task, env, "data copy", "core"):
        src, dst = data_dir(0) / "core" / "default", data_dir(env) / "core" / "default"
        if dst.exists():
            remove_tree(dst)
        dst.mkdir(parents=True)
        for item in src.iterdir():
            if item.name in CORE_SKIP:
                continue
            if item.name == "db":
                (dst / "db").mkdir()
                for db in item.iterdir():
                    if db.suffix == ".db" and db.is_file() and db.name != "graphiti_kuzu.db":
                        copy_db(db, dst / "db" / db.name)
                    elif db.is_dir():  # the vector store, small
                        shutil.copytree(db, dst / "db" / db.name)
                    else:  # Kuzu's file can't be read while env0's core runs: copied when it can be
                        with contextlib.suppress(OSError):
                            shutil.copy2(db, dst / "db" / db.name)
            elif item.is_dir():
                shutil.copytree(item, dst / item.name)
            else:
                shutil.copy2(item, dst / item.name)
    write_env_dev(env)
    configure(env, task)


def fresh_base(repo: str, task: str | None) -> str:
    """A repo's base for a new branch: env0's dev/main, first brought up to GitHub when it can fast-forward."""
    d = repo_dir(0, repo)
    git(d, "fetch", "-q", "origin", check=False)
    main = main_of(repo)
    behind = int(git(d, "rev-list", "--count", f"{main}..origin/{main}", check=False) or 0)
    if behind:
        branch = git(d, "branch", "--show-current")
        # A fast-forward that would touch someone's uncommitted edits is refused by git: env0's dev/main is then
        # used as it is, and the branch catches up with GitHub when it lands.
        moved = branch == main and subprocess.run(
            ["git", "-C", str(d), "merge", "--ff-only", "-q", f"origin/{main}"], capture_output=True).returncode == 0
        if not moved:
            say(f"  ! env0's {repo} is {behind} commit(s) behind GitHub and wasn't brought up: its {main} is used.")
    return git(d, "rev-parse", main)


# ------------------------------------------------------------------------------------------------------- the verbs


def part_of_name(value: str | None) -> str:
    """--part-of as given: a task's id (open or done) stands for its title; anything else is the name itself."""
    value = (value or "").strip()
    for p in (task_path(value), TASKS / "done" / f"{value}.json"):
        if value and p.exists():
            with contextlib.suppress(OSError, ValueError):
                return json.loads(p.read_text(encoding="utf-8")).get("title") or value
    return value


def cmd_start(a) -> None:
    with locked():
        tasks = load_tasks()
        if task_path(a.task).exists():
            raise Stop(f"Task '{a.task}' is already open.")
        repos = expand(a.repos.split(","), a.kit)
        env = pick_env(repos, tasks, a.env)
        task = Task(id=a.task, title=a.title or a.task, env=env, repos=repos,
                    real=[k for k, on in ((data.READS, not a.no_real_reads), (data.WRITES, a.real_writes),
                                          (data.AI, a.real_ai)) if on],
                    part_of=part_of_name(a.part_of), about=(a.about or "").strip(),
                    created=datetime.now().astimezone().isoformat(timespec="seconds"))
        save(task)  # the claim holds from here
    event(task=task.id, env=env, step="task", phase="start", repos=repos, title=task.title,
          **({"part_of": task.part_of} if task.part_of else {}), **({"about": task.about} if task.about else {}))
    try:
        if env == 0:
            for repo in repos:
                d = repo_dir(0, repo)
                branch = git(d, "branch", "--show-current")
                if branch != main_of(repo):
                    raise Stop(f"env0's {repo} is on '{branch}', not {main_of(repo)}: tell Michel.")
                with step(task.id, 0, "pull", repo):
                    git(d, "fetch", "-q", "origin", check=False)
                    git(d, "merge", "--ff-only", "-q", f"origin/{main_of(repo)}", check=False)
                task.base[repo] = git(d, "rev-parse", "HEAD")
                task.before[repo] = dirty(d)
        else:
            init_env(env, task.id)
            for repo in REPOS:
                base = fresh_base(repo, task.id)
                d = repo_dir(env, repo)
                if dirty(d):
                    raise Stop(f"env{env}'s {repo} has uncommitted files: it isn't free (hiro-work sweep).")
                with step(task.id, env, "switch", repo):
                    if repo in repos:
                        git(d, "switch", "-q", "-C", task.branch, base)
                        task.base[repo] = base
                    else:
                        git(d, "switch", "-q", "--detach", base)
            install_all(env, REPOS, task.id)
            refresh_data(env, task.id)
        save(task)
    except BaseException:
        with locked():
            task_path(task.id).unlink(missing_ok=True)  # no half-made claim
        raise
    card(task)
    say_overlaps(task)


# ----------------------------------------------------------------------------------- claims at every step (fresh)


def overlaps(task: Task, tasks: list[Task] | None = None) -> list[str]:
    """Other open tasks that change what this one does: the same repos, or the core's kits beside an app that reads
    them. Said at every solid step (start, each commit, land, finish), since another task can start at any time."""
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
        say(f"  note: {line}. Whichever lands second merges the other's work first.")


def bring_up_others(env: int, task: Task) -> list[str]:
    """An environment's repos its task doesn't claim follow env0: each moves forward to env0's dev/main when it is
    clean and behind, so checks read today's core and kits (a kit changed in env0 meanwhile, as on Mon, Nov 16, 2026,
    broke a land in env1). A repo with uncommitted files is left as it is, and said."""
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
        target = git(repo_dir(0, repo), "rev-parse", main_of(repo))
        head = git(d, "rev-parse", "HEAD")
        if head == target:
            continue
        ahead = subprocess.run(["git", "-C", str(d), "merge-base", "--is-ancestor", head, target]).returncode == 0
        if not ahead:
            notes.append(f"{repo}: not behind env0's {main_of(repo)}, left as it is")
            continue
        git(d, "switch", "-q", "--detach", target)
        notes.append(f"{repo}: brought up to env0's {main_of(repo)} ({target[:8]})")
    return notes


def task_for_dir(path: Path) -> tuple[int, str, Task | None] | None:
    """The environment, repo and working task that claims it, for a folder inside C:\\hiro\\envN\\<repo>."""
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
    """The commit hook's step (build-kit/git-hooks/pre-commit): a commit belongs to a task that claims the repo here;
    other tasks on the same repos are named; the environment's other repos follow env0 before the check runs."""
    found = task_for_dir(Path(a.path))
    if found is None:
        return  # not a Hiro environment's repo
    env, repo, task = found
    if task is None:
        raise Stop(f"no task claims env{env}'s {repo}: a commit belongs to a task. Start one "
                   f"(`C:\\hiro\\bin\\hiro-work.cmd start <task> --repos {repo}`), or add the repo to yours "
                   f"(`C:\\hiro\\bin\\hiro-work.cmd claim <task> {repo}`).")
    say_overlaps(task)
    for line in bring_up_others(env, task):
        say(f"  {line}")


def cmd_claim(a) -> None:
    """Add repos to an open task (a change turned out to reach one more repo), free in its environment."""
    with locked():
        task = get(a.task)
        if task.state != "working" or task.env is None:
            raise Stop(f"Task {task.id} isn't working in an environment (it is {task.state}).")
        new = [r for r in expand(a.repos.split(","), a.kit) if r not in task.repos]
        if not new:
            say(f"Task {task.id} claims {', '.join(task.repos)} already.")
            return
        held = {r: t for r, t in claims_in(task.env, load_tasks()).items() if r in new and t != task.id}
        if held:
            raise Stop("Claimed already: " + ", ".join(f"{r} by {t}" for r, t in held.items()) + ".")
        env = task.env
        for repo in new:
            d = repo_dir(env, repo)
            if env == 0:
                task.base[repo] = git(d, "rev-parse", "HEAD")
                task.before[repo] = dirty(d)
            else:
                if dirty(d):
                    raise Stop(f"env{env}'s {repo} has uncommitted files: it isn't free (hiro-work sweep).")
                base = fresh_base(repo, task.id)
                git(d, "switch", "-q", "-C", task.branch, base)
                task.base[repo] = base
            task.repos.append(repo)
        save(task)
    event(task=task.id, env=task.env, step="claim", phase="end", ok=True, repos=new)
    say(f"Task {task.id} now claims {', '.join(task.repos)}.")
    say_overlaps(task)


def card(task: Task) -> None:
    p = ports(task.env) if task.env is not None else {}
    where = env_dir(task.env) if task.env is not None else "(parked)"
    say("")
    say(f"Task {task.id}" + (f" (part of {task.part_of})" if task.part_of else "")
        + f": env{task.env} | claims {', '.join(task.repos)} | {where}")
    if task.about:
        say(f"  {task.about}")
    if task.env:
        say(f"  branch {task.branch} | data {data_dir(task.env)} | ports {min(p.values())}-{min(p.values()) + appfile.BLOCK - 1}")
        say(f"  {data.describe(task.real)}")


def cmd_real(a) -> None:
    """Change which real systems a task's copy reaches: the data is copied again from env0 (servers down)."""
    task = get(a.task)
    if not task.env:
        raise Stop("env0 is real already; a parked task changes this when it resumes.")
    up = [n for n, s in servers(task.env).items() if listening(s.port)]
    if up:
        raise Stop(f"env{task.env}'s servers are up ({', '.join(up)}): hiro-work down {task.env} first.")
    with locked():
        task.real = [k for k, on in ((data.READS, a.reads), (data.WRITES, a.writes), (data.AI, a.ai)) if on]
        save(task)
    refresh_data(task.env, task.id)
    card(task)


def cmd_move(a) -> None:
    with locked():
        tasks = load_tasks()
        task = get(a.task)
        if task.env != 0:
            raise Stop(f"Task {task.id} is in env{task.env}, not env0.")
        env = pick_env(task.repos, [t for t in tasks if t.id != task.id] + [], None)
        if env == 0:
            env = next(e for e in ENVS if e and e not in {t.env for t in tasks if t.state == "working"})
        task.env = env
        save(task)
    init_env(env, task.id)
    for repo in REPOS:
        src, dst = repo_dir(0, repo), repo_dir(env, repo)
        base = git(src, "rev-parse", "HEAD")
        with step(task.id, env, "move", repo):
            if repo in task.repos:
                # Only the task's own files move; what was there before it started stays in env0
                own = [line[3:].split(" -> ")[-1].strip('"') for line in dirty(src)
                       if line not in task.before.get(repo, [])]
                stashed = bool(own)
                if stashed:
                    git(src, "stash", "push", "-u", "-q", "-m", f"hiro-work move {task.id}", "--", *own)
                git(dst, "switch", "-q", "-C", task.branch, base)
                if stashed:
                    git(dst, "stash", "pop", "-q")
                task.base[repo] = base
            else:
                git(dst, "switch", "-q", "--detach", base)
    install_all(env, REPOS, task.id)
    refresh_data(env, task.id)
    save(task)
    event(task=task.id, env=env, step="moved", phase="end", ok=True, repos=task.repos)
    card(task)


def cmd_finish(a) -> None:
    task = get(a.task)
    if task.env != 0:
        raise Stop(f"Task {task.id} is in env{task.env}: it lands (hiro-work land {task.id}).")
    say_overlaps(task)
    left = {r: [f for f in dirty(repo_dir(0, r)) if f not in task.before.get(r, [])] for r in task.repos}
    left = {r: files for r, files in left.items() if files}
    if left:
        raise Stop("Not committed yet: " + "; ".join(f"{r}: {len(f)} file(s)" for r, f in left.items())
                   + ". Check, commit this task's files, then finish.")
    for repo in task.repos:  # what it committed in env0 since it started
        record_commits(task.id, 0, repo, task.base.get(repo), git(repo_dir(0, repo), "rev-parse", "HEAD"), "finish")
    with locked():
        task.state = "done"
        save(task)
    event(task=task.id, env=0, step="task", phase="end", ok=True)
    say(f"Task {task.id} finished: env0's {', '.join(task.repos)} are free.")


def kit_changed(env: int, task: Task) -> bool:
    if "hiroleague" not in task.repos:
        return False
    base = task.base.get("hiroleague")
    changed = git(repo_dir(env, "hiroleague"), "diff", "--name-only", f"{base}..HEAD", "--", *KIT_PATHS)
    return bool(changed)


def cmd_land(a) -> None:
    task = get(a.task)
    env = task.env
    if not env:
        raise Stop(f"Task {task.id} is in env0: it finishes (hiro-work finish {task.id}).")
    for repo in task.repos:
        if dirty(repo_dir(env, repo)):
            raise Stop(f"env{env}'s {repo} has uncommitted files: commit them on {task.branch} first.")
    say_overlaps(task)
    if a.wait:
        wait_for_env0(task, a.wait)
    # Landing is one step with its own inside (CodeHiro shows the task as landing while it runs)
    with step(task.id, env, "land"):
        for line in bring_up_others(env, task):
            say(f"  {line}")
        land_steps(task, env)
    # 5. Free the environment, keep it warm
    for repo in task.repos:
        d = repo_dir(env, repo)
        git(d, "switch", "-q", "--detach", main_of(repo))
        git(d, "branch", "-q", "-D", task.branch)
    with step(task.id, env, "servers down"):
        servers_down(env)
    with locked():
        task.state = "done"
        save(task)
    event(task=task.id, env=env, step="task", phase="end", ok=True, landed=True)
    say(f"Task {task.id} landed: {', '.join(task.repos)} in env0; env{env} is free. Not pushed: the deploy train "
        "pushes.")


def held_in_env0(task: Task) -> dict[str, str]:
    """The task's repos that a task in env0 holds with unfinished edits: landing would move env0 under them."""
    return {r: t for r, t in claims_in(0, load_tasks()).items() if r in task.repos and dirty(repo_dir(0, r))}


def wait_for_env0(task: Task, minutes: int) -> None:
    """land --wait: wait (checking every 20 s) until no env0 task holds one of these repos with unfinished edits."""
    deadline = time.monotonic() + minutes * 60
    held = held_in_env0(task)
    if held:
        say("Waiting for env0: " + ", ".join(f"{r} (task {t})" for r, t in held.items()) + f", up to {minutes} min.")
    while held and time.monotonic() < deadline:
        time.sleep(20)
        held = held_in_env0(task)
    if held:
        raise Stop(f"env0 still holds {', '.join(held)} after {minutes} min: land again later.")


def land_steps(task: Task, env: int) -> None:
    """Merge the latest, check, then fast-forward env0 (cmd_land's own steps)."""
    # 1. Bring each branch up to GitHub and to env0's dev/main
    for repo in task.repos:
        d = repo_dir(env, repo)
        with step(task.id, env, "merge latest", repo):
            git(d, "fetch", "-q", "origin", check=False)
            for ref in (f"origin/{main_of(repo)}", main_of(repo)):
                out = subprocess.run(["git", "-C", str(d), "merge", "--no-edit", "-q", ref], capture_output=True,
                                     text=True)
                if out.returncode != 0:
                    git(d, "merge", "--abort", check=False)
                    raise Stop(f"{repo}: merging {ref} into {task.branch} conflicts. Resolve it in {d}, commit, "
                               "then land again.")
    # 2. The checks, one repo at a time (each already uses every core)
    to_check = [r for r in task.repos if (repo_dir(env, r) / "scripts" / "check.sh").exists()]
    if kit_changed(env, task):
        to_check += [r for r in KIT_READERS if r not in to_check]
    failed = []
    for repo in to_check:
        install(env, repo, task.id)
        # An app beside a changed kit: its parts name the core files they read (@hiroleague:...), so the check runs
        # exactly the parts the kit change reaches
        log = LOGS / "check" / f"{task.id}-{repo}.log"
        with step(task.id, env, "check", repo, log=log) as outcome:
            out = subprocess.run([bash(), "-lc", "./scripts/check.sh"], cwd=repo_dir(env, repo),
                                 capture_output=True, text=True, encoding="utf-8", errors="replace")
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(out.stdout + out.stderr, encoding="utf-8")
            if out.returncode != 0:
                failed.append(f"{repo} (log: {log})")
                outcome.fail(f"check.sh failed (log: {log})")
    if failed:
        raise Stop("Checks failed: " + "; ".join(failed) + ". Fix, commit, land again.")
    # 3. Wait for nobody: refuse when a task in env0 holds one of these repos with unfinished edits
    held = held_in_env0(task)
    if held:
        raise Stop("env0 has unfinished edits in " + ", ".join(f"{r} (task {t})" for r, t in held.items())
                   + ": landing waits until that task finishes.")
    # 4. dev/main moves to the branch; env0's checkouts follow (a fast-forward)
    for repo in task.repos:
        with step(task.id, env, "fast-forward", repo):
            before = git(repo_dir(0, repo), "rev-parse", "HEAD")
            git(repo_dir(0, repo), "merge", "--ff-only", "-q", task.branch)
            record_commits(task.id, env, repo, before, git(repo_dir(0, repo), "rev-parse", "HEAD"), "land")
            install(0, repo, task.id)


def cmd_park(a) -> None:
    task = get(a.task)
    if not task.env:
        raise Stop("Only a task in env1..env5 parks; a task in env0 moves first (hiro-work move).")
    env = task.env
    for repo in task.repos:
        d = repo_dir(env, repo)
        if dirty(d):
            git(d, "add", "-A")
            git(d, "commit", "-q", "--no-verify", "-m", f"WIP (parked) {task.id}")
        git(d, "switch", "-q", "--detach", main_of(repo))
    with step(task.id, env, "servers down"):
        servers_down(env)
    with locked():
        task.state, task.env = "parked", None
        save(task)
    event(task=task.id, env=env, step="parked", phase="end", ok=True)
    say(f"Task {task.id} parked on {task.branch}; env{env} is free.")


def cmd_resume(a) -> None:
    with locked():
        tasks = load_tasks()
        task = get(a.task)
        if task.state != "parked":
            raise Stop(f"Task {task.id} isn't parked.")
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
            if git(d, "log", "-1", "--format=%s").startswith("WIP (parked)"):
                git(d, "reset", "-q", "--soft", "HEAD~1")
                git(d, "reset", "-q")
        else:
            git(d, "switch", "-q", "--detach", main_of(repo))
    install_all(env, REPOS, task.id)
    refresh_data(env, task.id)
    if a.part_of is not None:
        with locked():
            task.part_of = part_of_name(a.part_of)
            save(task)
    event(task=task.id, env=env, step="resumed", phase="end", ok=True,
          **({"part_of": task.part_of} if a.part_of is not None else {}))
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
    }
    if env:  # the provider keys in the PC's environment, blanked unless the task asks for AI (data.py)
        out["core"].env.update(data.core_env(dict(os.environ), real_of(env)))
    for a in appfile.APPS:  # each app as apps.toml says
        api, ui, repo = p[f"{a.repo}-api"], p[f"{a.repo}-ui"], here / a.repo
        fill = {"port": str(api), "data": str(app_data(env, a)), "repo": "{repo}"}  # {repo} stays for the app
        out[f"{a.repo}-api"] = Server(
            f"{a.repo}-api", repo / a.backend, a.api.format(**fill), api,
            {"PYTHONUTF8": "1", **{k: v.format(**fill) for k, v in a.api_env.items()}}, repo / ".env.dev")
        # --host: 127.0.0.1 only, as every app (Vite's default "localhost" is IPv6-only on this PC)
        out[f"{a.repo}-ui"] = Server(f"{a.repo}-ui", repo / a.frontend,
                                     f"npm.cmd run dev -- --port {ui} --strictPort --host 127.0.0.1", ui,
                                     {a.ui_api_env: f"http://127.0.0.1:{api}"})
    return out


def pick_servers(env: int, names: list[str]) -> list[Server]:
    """Names: a server ("homehiro-ui"), an app or "core" (both of its servers). None given: the core and the apps
    the environment's task claims, or the core and every app when it has no task."""
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
        return con.execute("select 1 from extensions where extension_id = ?", (ext_id,)).fetchone() is not None
    finally:
        con.close()


def pair_apps(env: int, apps: list[appfile.App]) -> None:
    """Pair apps with the environment's running core (pair_apps.py, in the core's own environment), one at a time."""
    url = f"ws://127.0.0.1:{ports(env)['core-socket']}"
    args = [f"{x.name}={app_data(env, x) / 'hiroleague'}" for x in apps]
    out = subprocess.run(["uv", "run", "python", str(Path(__file__).with_name("pair_apps.py")),
                          str(core_workspace(env)), url, *args],
                         cwd=repo_dir(env, "hiroleague") / "hiroserver", capture_output=True, text=True)
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
    for s in chosen:
        mark = "up  " if s not in waiting else "NOT UP"
        say(f"  {mark} {s.name:16} http://127.0.0.1:{s.port}   log: {LOGS / f'env{env}' / f'{s.name}.log'}")
    if waiting:
        raise Stop("Some servers didn't answer in time: read their logs (or their tabs in the hiro-env window).")


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
    if any(s.name == "core" for s in chosen):  # the core's other three listeners
        port_list += [ports(env)[k] for k in ("core-socket", "core-http", "core-plugin")]
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
        what = "; ".join((f"{t.part_of} › " if t.part_of else "") + f"{t.id} ({', '.join(t.repos)})" for t in here)             or ("Michel's dev" if env == 0 else "free")
        exists = env == 0 or (env_dir(env) / "hiroleague" / ".git").exists()
        say(f"  env{env}  {'' if exists else '(not made yet) '}{what}" + (f"  | up: {', '.join(up)}" if up else ""))
    parked = [t for t in tasks if t.state == "parked"]
    if parked:
        say("Parked: " + ", ".join(f"{t.id} ({t.updated[:10]})" for t in parked))


def merged_left(listing: str, main: str) -> list[str]:
    """The merged branches left behind, from `git branch --merged`: not the main branch, and not one checked out here
    ("*") or in another worktree ("+", an open task's branch in env1..env5: it is in use, not left)."""
    out = []
    for line in listing.splitlines():
        if line[:1] in ("*", "+"):
            continue
        b = line.strip()
        if b and b not in (main, "main", "dev") and not b.startswith("("):
            out.append(b)
    return out


def cmd_sweep(a) -> None:
    say("Left behind (nothing is removed here):")
    findings: list[dict] = []

    def found(kind: str, repo: str, what: str, fix: str) -> None:
        say(f"  {repo}: {what}")
        findings.append({"kind": kind, "where": repo, "what": what, "since": None, "fix": fix})

    for repo in REPOS:
        d = repo_dir(0, repo)
        for block in git(d, "worktree", "list", "--porcelain").split("\n\n"):
            path = block.splitlines()[0].removeprefix("worktree ").replace("/", "\\")
            if path.lower() == str(d).lower() or path.lower().startswith(str(ROOT).lower() + "\\env"):
                continue
            found("worktree", repo, f"worktree outside C:\\hiro\\env1-5: {path}", f"git -C {d} worktree remove {path}")
        main = main_of(repo)
        merged = merged_left(git(d, "branch", "--merged", main), main)
        if merged:
            found("merged", repo, f"{len(merged)} merged branch(es) kept: {', '.join(merged)}",
                  f"git -C {d} branch -d {' '.join(merged)}")
        branch = git(d, "branch", "--show-current")
        if branch != main:
            found("off-main", repo, f"env0 checkout is on '{branch}', not {main}", f"git -C {d} switch {main}")
    if not findings:
        say("  nothing")
    # CodeHiro's Sweep shows the last report, beside the parked tasks and the servers left up it works out itself
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


# ---------------------------------------------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="hiro-work", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("task")
    s.add_argument("--repos", required=True)
    s.add_argument("--kit", action="store_true", help="a kit, SDK or build-kit change: also claims the apps")
    s.add_argument("--title")
    s.add_argument("--env", type=int, choices=list(ENVS))
    s.add_argument("--part-of", help="the bigger work it is a piece of: a name, or a task's id (its title is used)")
    s.add_argument("--about", help="what it does, in a sentence (the Work area shows it under its name)")
    s.add_argument("--no-real-reads", action="store_true",
                   help="env1..5: read no real system (HA, Frigate, MQTT, health checks), which they do by default")
    s.add_argument("--real-writes", action="store_true",
                   help="env1..5: keep the logins that write (TrainHiro's Frigate, NetHiro's AdGuard rules)")
    s.add_argument("--real-ai", action="store_true", help="env1..5: keep the copied AI providers")
    for verb in ("move", "finish", "park", "review"):
        sub.add_parser(verb).add_argument("task")
    ld = sub.add_parser("land", help="envN: merge the latest, check, fast-forward env0, free the environment")
    ld.add_argument("task")
    ld.add_argument("--wait", type=int, nargs="?", const=120, default=0, metavar="MINUTES",
                    help="when env0 holds one of its repos with unfinished edits, wait for it (default 120 min)")
    cl = sub.add_parser("claim", help="add repos to an open task (free in its environment)")
    cl.add_argument("task")
    cl.add_argument("repos", help="comma-separated")
    cl.add_argument("--kit", action="store_true", help="a kit change: the apps that read it too")
    fr = sub.add_parser("fresh", help="the commit hook's check: the commit's task, overlaps, the other repos")
    fr.add_argument("path", help="a folder inside the repo being committed")
    ds = sub.add_parser("describe", help="change what an open task does (--about) or what it is part of (--part-of)")
    ds.add_argument("task")
    ds.add_argument("--about", help="what it does, in a sentence; \"\" clears it")
    ds.add_argument("--part-of", help="the bigger work it is a piece of; \"\" makes it a task of its own")
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
    sub.add_parser("status")
    sub.add_parser("sweep")
    rl = sub.add_parser("real", help="env1..5: which real systems a task's copy reaches (copies the data again)")
    rl.add_argument("task")
    rl.add_argument("--reads", action="store_true")
    rl.add_argument("--writes", action="store_true")
    rl.add_argument("--ai", action="store_true")
    rl.set_defaults(func=cmd_real)
    rd = sub.add_parser("refresh-data", help="live -> env0: fetch a scrubbed live copy; --apply puts it in env0")
    rd.add_argument("--apply", metavar="STAMP", help="a copy in C:\\hiro\\data\\live-copies, or 'latest'")
    rd.add_argument("--files", action="store_true", help="only the picture folders (avatars, StudyHiro's files)")
    rd.set_defaults(func=lambda a: data.cmd_refresh_data(a, sys.modules[__name__]))
    # The deploy train lives in train.py, which imports this module: run as a script, this is __main__, so it is
    # named hiro_work too, or train.py would load a second copy (and its Stop wouldn't be caught here)
    sys.modules.setdefault("hiro_work", sys.modules[__name__])
    import train
    train.add_parser(sub)
    a = p.parse_args(argv)
    try:
        if getattr(a, "func", None):
            return a.func(a) or 0
        {"start": cmd_start, "move": cmd_move, "finish": cmd_finish, "land": cmd_land, "park": cmd_park,
         "resume": cmd_resume, "status": cmd_status, "sweep": cmd_sweep, "up": cmd_up, "down": cmd_down,
         "review": cmd_review, "describe": cmd_describe, "claim": cmd_claim, "fresh": cmd_fresh,
         "configure": lambda a: configure(a.env), "init": lambda a: init_env(a.env),
         "train": train.cmd_train}[a.cmd](a)
    except Stop as e:
        say(f"\nStopped: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
