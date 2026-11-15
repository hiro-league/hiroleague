r"""hiro-work: the environments every Hiro League task works in (hiro-docs standards/workflow.md).

Every task claims the repos it changes. It works in env0 (Michel's dev: the main checkouts in C:\hiro\env0) while
those repos are free there, else in one of env1..env5: the same repos as git worktrees, kept warm between tasks, each
with its own data (C:\hiro\data\envN) and its own block of ports (7N00-7N12). A task in env0 commits when it finishes;
a task in env1..env5 lands: its branches merge into dev/main and env0 is brought up to them.

    hiro-work status                         environments, tasks, claims, servers
    hiro-work start <task> --repos a,b [--kit] [--title ...] [--env N]
    hiro-work move <task>                    env0 -> a free environment, carrying the edits
    hiro-work finish <task>                  env0: every claimed repo committed; release the claims
    hiro-work land <task>                    env1..5: merge, check, update env0, free the environment
    hiro-work park <task> / resume <task>    save the work on its branch and free the environment / take one back
    hiro-work up <env> [server ...] / down <env> [server ...]   servers, in Windows Terminal outside Claude
    hiro-work init <env>                     make (or repair) an environment: worktrees, installs, settings
    hiro-work sweep                          what is left behind (report only)
    hiro-work train [repo ...] [--dry-run]   the deploy train: push and deploy, when Michel says (train.py)

State lives in C:\hiro\tasks (one JSON file per task) and every step is logged to C:\hiro\logs\events.jsonl (with
its time) for CodeHiro's Work area. Standard library only: it runs on the system Python.
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

ROOT = Path(os.environ.get("HIRO_ROOT", r"C:\hiro"))
TASKS = ROOT / "tasks"
LOGS = ROOT / "logs"
EVENTS = LOGS / "events.jsonl"
ENVS = range(0, 6)

# The repos every environment holds, the core first (it lands first). hiroleague-website lives in env0 only.
REPOS = ["hiroleague", "homehiro", "nethiro", "trainhiro", "studyhiro", "codehiro", "aicam", "hiro-docs"]
MAIN = {"hiroleague": "dev", "hiro-docs": "dev"}  # every other repo's main branch is main
# The apps that read the core's kits, SDK and build kit (../hiroleague): a change there claims them too.
KIT_READERS = ["homehiro", "nethiro", "trainhiro", "studyhiro", "codehiro"]
KIT_PATHS = ["hiroserver/hiro-extension-kit", "hiroserver/hiro-channel-sdk", "hiroserver/hiro-commons",
             "ui-kit", "build-kit"]
# What each repo installs, and the lock file that says when to install again
PYTHON = {"hiroleague": ["hiroserver"], "homehiro": ["backend"], "nethiro": ["backend"], "trainhiro": ["backend"],
          "studyhiro": ["backend"], "codehiro": ["scc_report"]}
NODE = {"hiroleague": ["admin_frontend", "ui-kit"], "homehiro": ["frontend"], "nethiro": ["frontend"],
        "trainhiro": ["frontend"], "studyhiro": ["frontend"], "codehiro": ["history-dashboard"]}
# Each app's data folder name in C:\hiro\data\envN (the core's is "core")
APPS = ["homehiro", "nethiro", "trainhiro", "studyhiro"]
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
    """The environment's block: 7N00-7N14, in a fixed order (workflow.md, Ports). The core listens on four: its
    admin API, the apps' extension socket, its HTTP status API and the channel plugins' socket."""
    names = ["core-admin", "core-socket", "core-ui", "homehiro-api", "homehiro-ui", "nethiro-api", "nethiro-ui",
             "trainhiro-api", "trainhiro-ui", "studyhiro-api", "studyhiro-ui", "codehiro-api", "codehiro-ui",
             "core-http", "core-plugin"]
    return {name: 7000 + 100 * env + i for i, name in enumerate(names)}


def workspace_name(env: int) -> str:
    """The core's workspace for an environment, in the machine's one workspace registry."""
    return "default" if env == 0 else f"env{env}"


# ---------------------------------------------------------------------------------------------------------- output


def say(msg: str) -> None:
    print(msg, flush=True)


def event(**fields) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    fields = {"at": datetime.now().astimezone().isoformat(timespec="seconds"), **fields}
    with open(EVENTS, "a", encoding="utf-8") as f:
        f.write(json.dumps(fields) + "\n")


@contextlib.contextmanager
def step(task: str | None, env: int | None, name: str, repo: str | None = None):
    """One timed step: printed, and logged as a start and an end event."""
    label = f"{name}" + (f" [{repo}]" if repo else "")
    say(f"> {label}")
    event(task=task, env=env, repo=repo, step=name, phase="start")
    t = time.monotonic()
    try:
        yield
    except BaseException as e:
        s = round(time.monotonic() - t, 1)
        event(task=task, env=env, repo=repo, step=name, phase="end", ok=False, seconds=s, error=str(e)[:300])
        say(f"x {label} failed after {s} s")
        raise
    s = round(time.monotonic() - t, 1)
    event(task=task, env=env, repo=repo, step=name, phase="end", ok=True, seconds=s)
    say(f"  done in {s} s")


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


def install_all(env: int, repos: list[str], task: str | None = None) -> None:
    """Every repo's installs, one at a time: measured, side by side is no faster (npm ci is disk-bound: 13-17 s
    each alone, 58-104 s each when seven run at once), and one at a time keeps the output readable."""
    for repo in repos:
        install(env, repo, task)


ENV_DEV_FORCED = {"OUTPUTS": "off", "HA_AUTO_WRITES": "off", "AUTH": "off"}


def write_env_dev(env: int) -> None:
    """Each app's .env.dev in envN: env0's, with this environment's data folder, no sends or HA writes, and sign-in
    off (everyone is the owner, so the built-in browser can show its pages)."""
    for app in APPS:
        src = repo_dir(0, app) / ".env.dev"
        lines = src.read_text(encoding="utf-8").splitlines() if src.exists() else []
        forced = {**ENV_DEV_FORCED, "DATA_DIR": (data_dir(env) / app).as_posix()}
        keep = [ln for ln in lines if ln.split("=", 1)[0].strip() not in forced]
        keep += [f"{k}={v}" for k, v in forced.items()]
        (repo_dir(env, app) / ".env.dev").write_text("\n".join(keep) + "\n", encoding="utf-8")


def set_setting(db: Path, key: str, value: str) -> None:
    with sqlite3.connect(db) as con:
        con.execute("insert into setting(key, value) values (?, ?) on conflict(key) do update set value = excluded.value",
                    (key, value))


def configure(env: int, task: str | None = None) -> None:
    """Point an environment's copies at its own ports: the core's listeners (its workspace's config.json), each
    app's link to the core. In env1..env5 also: the copied WhatsApp channel off (two clients on one account break
    it), LAN names off, and the core's workspace registered under its own name."""
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
        for app in APPS:
            db = data_dir(env) / app / f"{app}.db"
            if not db.exists():
                continue
            with sqlite3.connect(db) as con:
                if not con.execute("select 1 from sqlite_master where name = 'setting'").fetchone():
                    continue
            set_setting(db, "hiroleague_url", f"ws://127.0.0.1:{p['core-socket']}")
            if env:
                set_setting(db, "hiroleague_admin_url", f"http://127.0.0.1:{p['core-ui']}")
                set_setting(db, f"{app}_url", f"http://127.0.0.1:{p[app + '-ui']}")
        if env:
            with sqlite3.connect(ws / "db" / "workspace.db") as con:
                con.execute("update channel_plugins set enabled = 0")
            if workspace_name(env) not in registry_names():
                run(["uv", "run", "hiro", "workspaces", "create", workspace_name(env), "--path", str(ws)],
                    cwd=repo_dir(env, "hiroleague") / "hiroserver")


def registry_names() -> set[str]:
    reg = Path(os.environ["LOCALAPPDATA"]) / "hiro" / "registry.json"
    return {w["name"] for w in json.loads(reg.read_text(encoding="utf-8"))["workspaces"].values()}


def copy_db(src: Path, dst: Path) -> None:
    """A consistent copy of a SQLite database, even while env0's server writes to it (what's in the WAL comes too)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.unlink(missing_ok=True)
    with sqlite3.connect(f"file:{src.as_posix()}?mode=ro", uri=True) as a, sqlite3.connect(dst) as b:
        a.backup(b)


def refresh_data(env: int, task: str | None = None) -> None:
    """envN's data from env0's: the databases copied, the big folders left out (workflow.md, Data)."""
    if env == 0:
        return
    for app in APPS:
        src, dst = data_dir(0) / app, data_dir(env) / app
        with step(task, env, "data copy", app):
            if dst.exists():
                shutil.rmtree(dst)
            dst.mkdir(parents=True)
            for db in src.glob("*.db"):
                copy_db(db, dst / db.name)
            # The app's link to the core: its key and identity (the core copy below knows the same key)
            if (src / "hiroleague").is_dir():
                shutil.copytree(src / "hiroleague", dst / "hiroleague")
    with step(task, env, "data copy", "core"):
        src, dst = data_dir(0) / "core" / "default", data_dir(env) / "core" / "default"
        if dst.exists():
            shutil.rmtree(dst)
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


def cmd_start(a) -> None:
    with locked():
        tasks = load_tasks()
        if task_path(a.task).exists():
            raise Stop(f"Task '{a.task}' is already open.")
        repos = expand(a.repos.split(","), a.kit)
        env = pick_env(repos, tasks, a.env)
        task = Task(id=a.task, title=a.title or a.task, env=env, repos=repos,
                    created=datetime.now().astimezone().isoformat(timespec="seconds"))
        save(task)  # the claim holds from here
    event(task=task.id, env=env, step="task", phase="start", repos=repos, title=task.title)
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


def card(task: Task) -> None:
    p = ports(task.env) if task.env is not None else {}
    where = env_dir(task.env) if task.env is not None else "(parked)"
    say("")
    say(f"Task {task.id}: env{task.env} | claims {', '.join(task.repos)} | {where}")
    if task.env:
        say(f"  branch {task.branch} | data {data_dir(task.env)} | ports {min(p.values())}-{max(p.values())}")


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
    left = {r: [f for f in dirty(repo_dir(0, r)) if f not in task.before.get(r, [])] for r in task.repos}
    left = {r: files for r, files in left.items() if files}
    if left:
        raise Stop("Not committed yet: " + "; ".join(f"{r}: {len(f)} file(s)" for r, f in left.items())
                   + ". Check, commit this task's files, then finish.")
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
        with step(task.id, env, "check", repo):
            out = subprocess.run([bash(), "-lc", "./scripts/check.sh"], cwd=repo_dir(env, repo),
                                 capture_output=True, text=True, encoding="utf-8", errors="replace")
            log = LOGS / "check" / f"{task.id}-{repo}.log"
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(out.stdout + out.stderr, encoding="utf-8")
            if out.returncode != 0:
                failed.append(f"{repo} (log: {log})")
    if failed:
        raise Stop("Checks failed: " + "; ".join(failed) + ". Fix, commit, land again.")
    # 3. Wait for nobody: refuse when a task in env0 holds one of these repos with unfinished edits
    held = {r: t for r, t in claims_in(0, load_tasks()).items() if r in task.repos and dirty(repo_dir(0, r))}
    if held:
        raise Stop("env0 has unfinished edits in " + ", ".join(f"{r} (task {t})" for r, t in held.items())
                   + ": landing waits until that task finishes.")
    # 4. dev/main moves to the branch; env0's checkouts follow (a fast-forward)
    for repo in task.repos:
        with step(task.id, env, "land", repo):
            git(repo_dir(0, repo), "merge", "--ff-only", "-q", task.branch)
            install(0, repo, task.id)
    # 5. Free the environment, keep it warm
    for repo in task.repos:
        d = repo_dir(env, repo)
        git(d, "switch", "-q", "--detach", main_of(repo))
        git(d, "branch", "-q", "-D", task.branch)
    servers_down(env)
    with locked():
        task.state = "done"
        save(task)
    event(task=task.id, env=env, step="task", phase="end", ok=True, landed=True)
    say(f"Task {task.id} landed: {', '.join(task.repos)} in env0; env{env} is free. Not pushed: the deploy train "
        "pushes.")


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
    event(task=task.id, env=env, step="resumed", phase="end", ok=True)
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
    for app in APPS:
        api, ui = p[f"{app}-api"], p[f"{app}-ui"]
        out[f"{app}-api"] = Server(
            f"{app}-api", here / app / "backend",
            f"uv run uvicorn {app}.main:app --reload --reload-dir src --port {api} --timeout-graceful-shutdown 3",
            api, {"PYTHONUTF8": "1"}, here / app / ".env.dev")
        # --host: 127.0.0.1 only, as every app (Vite's default "localhost" is IPv6-only on this PC)
        out[f"{app}-ui"] = Server(f"{app}-ui", here / app / "frontend",
                                  f"npm.cmd run dev -- --port {ui} --strictPort --host 127.0.0.1", ui,
                                  {f"{app.upper()}_API": f"http://127.0.0.1:{api}"})
    return out


def pick_servers(env: int, names: list[str]) -> list[Server]:
    """Names: a server ("homehiro-ui"), an app or "core" (both of its servers). None given: the core and the apps
    the environment's task claims, or the core and every app when it has no task."""
    every = servers(env)
    if not names:
        held = [t for t in load_tasks() if t.state == "working" and t.env == env]
        apps = sorted({r for t in held for r in t.repos if r in APPS}) if held and env else APPS
        names = ["core", *apps]
    chosen: list[Server] = []
    for n in names:
        group = [s for k, s in every.items() if k == n or k.startswith(n + "-")]
        if not group:
            raise Stop(f"No server '{n}'. Servers: {', '.join(every)}.")
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


def cmd_up(a) -> None:
    env = a.env
    if env and not (env_dir(env) / "hiroleague" / ".git").exists():
        raise Stop(f"env{env} isn't made yet (hiro-work init {env}).")
    chosen = [s for s in pick_servers(env, a.servers) if not listening(s.port)]
    if not chosen:
        say("Already running.")
        return
    wt = [shutil.which("wt.exe") or "wt.exe", "-w", f"hiro-env{env}"]
    for i, s in enumerate(chosen):
        if i:
            wt.append(";")
        wt += ["new-tab", "--title", f"env{env} {s.name}", "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
               "-File", str(runner(env, s))]
    with step(None, env, "servers up"):
        subprocess.Popen(wt, creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
        deadline = time.monotonic() + a.wait
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
    with step(None, a.env, "servers down"):
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
        what = "; ".join(f"{t.id} ({', '.join(t.repos)})" for t in here) or ("Michel's dev" if env == 0 else "free")
        exists = env == 0 or (env_dir(env) / "hiroleague" / ".git").exists()
        say(f"  env{env}  {'' if exists else '(not made yet) '}{what}" + (f"  | up: {', '.join(up)}" if up else ""))
    parked = [t for t in tasks if t.state == "parked"]
    if parked:
        say("Parked: " + ", ".join(f"{t.id} ({t.updated[:10]})" for t in parked))


def cmd_sweep(a) -> None:
    say("Left behind (nothing is removed here):")
    found = 0
    for repo in REPOS:
        d = repo_dir(0, repo)
        for block in git(d, "worktree", "list", "--porcelain").split("\n\n"):
            path = block.splitlines()[0].removeprefix("worktree ").replace("/", "\\")
            if path.lower() == str(d).lower() or path.lower().startswith(str(ROOT).lower() + "\\env"):
                continue
            say(f"  {repo}: worktree outside C:\\hiro\\env1-5: {path}")
            found += 1
        main = main_of(repo)
        merged = [b.strip("* ").strip() for b in git(d, "branch", "--merged", main).splitlines()]
        merged = [b for b in merged if b and b not in (main, "main", "dev") and not b.startswith("(")]
        if merged:
            say(f"  {repo}: {len(merged)} merged branch(es) kept")
            found += 1
        branch = git(d, "branch", "--show-current")
        if branch != main:
            say(f"  {repo}: env0 checkout is on '{branch}', not {main}")
            found += 1
    if not found:
        say("  nothing")


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
    for verb in ("move", "finish", "land", "park"):
        sub.add_parser(verb).add_argument("task")
    r = sub.add_parser("resume")
    r.add_argument("task")
    r.add_argument("--env", type=int, choices=[e for e in ENVS if e])
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
    # The deploy train lives in train.py, which imports this module: run as a script, this is __main__, so it is
    # named hiro_work too, or train.py would load a second copy (and its Stop wouldn't be caught here)
    sys.modules.setdefault("hiro_work", sys.modules[__name__])
    import train
    train.add_parser(sub)
    a = p.parse_args(argv)
    try:
        {"start": cmd_start, "move": cmd_move, "finish": cmd_finish, "land": cmd_land, "park": cmd_park,
         "resume": cmd_resume, "status": cmd_status, "sweep": cmd_sweep, "up": cmd_up, "down": cmd_down,
         "configure": lambda a: configure(a.env), "init": lambda a: init_env(a.env),
         "train": train.cmd_train}[a.cmd](a)
    except Stop as e:
        say(f"\nStopped: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
