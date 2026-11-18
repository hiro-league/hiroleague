r"""The PC's helper for CodeHiro's environment cards (workflow.md, "See your change running").

A card's Up or Down goes to CodeHiro (POST /api/work/asks). This helper, running on the PC from logon, asks CodeHiro
every few seconds for what is waiting (GET /api/work/asks/next, with the Work key the sender uses) and runs each ask:

    up <env> [servers]     hiro-work up <env> [servers]
    down <env> [servers]   hiro-work down <env> [servers]
    refresh                hiro-work refresh-data --now          (env0: a new live copy, applied)
    fetch                  hiro-work refresh-data                (a new live copy, env0 unchanged)
    apply <stamp>          hiro-work refresh-data --apply <stamp>
    data <env> <source>    hiro-work data <env> <source>         (env1..env5: env0, vanilla, live, live:<stamp>)

in a tab of the environment's own window (hiro-envN), so its output shows there; the servers' events then reach the
card. Work › Hiro-Audit's Run audit is the one other ask:

    audit                  claude "/hiro-doc-audit" in env0's hiro-docs, in a tab of the hiro-audit window

an interactive Claude session that audits what changed since the last run and records its report (audit.py); Michel
answers it there. Only these pass, with an environment 0 to 5 and the server names hiro-work knows; anything else is
refused and logged. One helper at a time (C:\hiro\run\relay.pid). Its log is C:\hiro\logs\relay.log. Standard library only.

Every minute it also says which repos each environment has changed (hiro_work.changed_repos): a "changes" event for
each environment whose list differs from the last one said (all of them when it starts), so the card can dim a claim
nothing has changed yet. The same event says what the environment holds that no task there owns
(hiro_work.leftovers: uncommitted files, a stray branch, commits off the trunk), shown at the card's foot, and where
its data came from (data.read_source: the card's data row); env0's also lists the live copies on the PC
(data.live_copy_list: its Data menu).

Every 10 minutes it looks at env0's data folders for what no copy list covers (data.survey): a "copy-lists" event,
with each listed item's size, when that differs from the last one said and at least every hour, shown in Work › Sweep
and Work › Data. The lists are read again each time, so a land's new lists count at once.

    pythonw relay.py              run (what the Startup shortcut starts)
    python relay.py --install     a shortcut in this Windows user's Startup folder ("Hiro League work relay": starts it
                                  at logon, no admin needed; Settings, Apps, Startup can switch it off), started now too
    python relay.py --uninstall   removes the shortcut and stops the helper
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hiro_work as hw  # noqa: E402
import ship  # noqa: E402

LAUNCHER = Path(r"C:\hiro\bin\hiro-work.cmd")
AUDIT_DIR = hw.ROOT / "env0" / "hiro-docs"  # where the audit's Claude session starts (the audit doc lives there)
LOG = hw.LOGS / "relay.log"
PID = hw.RUN / "relay.pid"
URL = ship.URL.rsplit("/events", 1)[0] + "/asks/next"  # http://reports.local/api/work/asks/next
EVERY_S = 3
CHANGES_EVERY_S = 60  # how often each environment's changed repos are looked at
DRIFT_EVERY_S = 600  # how often env0's data folders are compared with the copy lists
SIZES_EVERY_S = 3600  # how often env0's sizes are said when nothing else changed
NAME = "Hiro League work relay"
SHORTCUT = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / (
    NAME + ".lnk")


class Refused(Exception):
    pass


def check_data(ask: dict) -> tuple[str, int, list[str]]:
    """A Data menu's ask: (verb, the environment whose window runs it, hiro-work's arguments)."""
    verb = ask.get("verb")
    if verb == "refresh":
        return verb, 0, ["refresh-data", "--now"]
    if verb == "fetch":
        return verb, 0, ["refresh-data"]
    if verb == "apply":
        stamp = ask.get("stamp")
        try:
            hw.data.stamp_time(str(stamp))
        except ValueError:
            raise Refused(f"no live copy {stamp!r}") from None
        return verb, 0, ["refresh-data", "--apply", str(stamp)]
    env, source = ask.get("env"), str(ask.get("source") or "")
    if not isinstance(env, int) or not 1 <= env <= 5:
        raise Refused(f"no environment {env!r} for data (env1 to env5)")
    try:
        hw.data.parse_source(source)
    except ValueError as exc:
        raise Refused(str(exc)) from None
    return verb, env, ["data", str(env), source]


DATA_VERBS = ("refresh", "fetch", "apply", "data")


def check(ask: dict) -> tuple[str, int, list[str]]:
    """The command an ask is for: (verb, env, servers). Anything but a known up or down is refused."""
    verb, env, names = ask.get("verb"), ask.get("env"), ask.get("servers") or []
    if verb not in ("up", "down"):
        raise Refused(f"not up or down: {verb!r}")
    if not isinstance(env, int) or not 0 <= env <= 5:
        raise Refused(f"no environment {env!r}")
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        raise Refused(f"servers aren't names: {names!r}")
    known = set(hw.servers(env)) | set(hw.SERVED) | {"core"} | set(hw.PORT_ALIASES)
    unknown = [n for n in names if n not in known]
    if unknown:
        raise Refused(f"no server {', '.join(unknown)} in env{env}")
    return verb, env, names


def log(line: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat(timespec='seconds')} {line}\n")


def claude() -> str:
    """Claude Code's command: on the PATH, else where its installer puts it (a logon process may lack the PATH)."""
    return shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude.exe")


def run_audit() -> bool:
    """The doc audit, in Claude: a tab that stays open after it (cmd /k), so Michel reads and answers its report."""
    log("runs: claude /hiro-doc-audit")
    wt = [shutil.which("wt.exe") or "wt.exe", "-w", "hiro-audit", "new-tab", "--title", "doc audit", "-d",
          str(AUDIT_DIR), "cmd", "/k", claude(), "/hiro-doc-audit"]
    subprocess.Popen(wt, creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    return True


def run(ask: dict) -> bool:
    if ask.get("verb") == "audit":
        return run_audit()  # an audit ask carries nothing else: whatever else it holds is ignored
    try:
        if ask.get("verb") in DATA_VERBS:
            verb, env, args = check_data(ask)
            title = f"hiro-work {' '.join(args[:2])}"
        else:
            verb, env, names = check(ask)
            args = [verb, str(env), *names]
            title = f"hiro-work {verb}" + (f" {','.join(names)}" if names else "")
    except Refused as exc:
        log(f"refused: {exc}")
        return False
    log(f"runs: hiro-work {' '.join(args)}")
    # A tab of the environment's own window: the command's output stays there a minute, then the tab closes
    wt = [shutil.which("wt.exe") or "wt.exe", "-w", f"hiro-env{env}", "new-tab", "--title", title, "cmd", "/c",
          str(LAUNCHER), *args, "&", "timeout", "/t", "60"]
    subprocess.Popen(wt, creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    return True


def fetch(key: str) -> list[dict]:
    """What CodeHiro holds for the PC; [] when it can't be reached (said once in the log until it answers again)."""
    req = urllib.request.Request(URL, headers={"X-Work-Key": key})
    with urllib.request.urlopen(req, timeout=10) as r:
        return list(json.loads(r.read().decode("utf-8")).get("asks") or [])


def changes(said: dict[int, dict]) -> dict[int, dict]:
    """Each made environment's changed repos and its leftovers, and a "changes" event for each that differs from what
    was said."""
    tasks = hw.load_tasks()
    now: dict[int, dict] = {}
    for env in hw.ENVS:
        if env and not (hw.env_dir(env) / "hiroleague" / ".git").exists():
            continue  # not made yet: an event would make it look made
        now[env] = {"repos": hw.changed_repos(env, tasks), "leftovers": hw.leftovers(env, tasks),
                    "data": hw.data.read_source(hw, env)}
        if env == 0:
            now[env]["live_copies"] = hw.data.live_copy_list(hw)
        if said.get(env) != now[env]:
            hw.event(task=None, env=env, step="changes", phase="end", ok=True, **now[env])
    return now


def drift(said: list[dict] | None, said_at: float) -> tuple[list[dict], float]:
    """env0's files no copy list covers; a "copy-lists" event, measured, when that differs from what was said or the
    last one is an hour old. (what is said now, when it was said)"""
    lists = hw.data.load(hw.env_dir(0))
    now = hw.data.survey(hw, lists, "env0", measure=False)["unlisted"]
    if now != said or time.monotonic() - said_at >= SIZES_EVERY_S:
        measured = hw.data.survey(hw, lists, "env0")
        hw.event(task=None, env=None, step="copy-lists", phase="end", ok=True, place="env0", **measured)
        return measured["unlisted"], time.monotonic()
    return now, said_at


def serve() -> int:
    import train  # the lock's process check (alive), shared with the deploy train

    PID.parent.mkdir(parents=True, exist_ok=True)
    if PID.exists():
        with_pid = PID.read_text(encoding="utf-8").strip()
        if with_pid.isdigit() and int(with_pid) != os.getpid() and train.alive(int(with_pid)):
            return 0  # one helper at a time
    PID.write_text(str(os.getpid()), encoding="utf-8")
    log(f"started (process {os.getpid()}), asking {URL}")
    down = False
    said: dict[int, dict] = {}
    said_drift: list[dict] | None = None
    looked = drifted = said_drift_at = 0.0
    while True:
        if time.monotonic() - looked >= CHANGES_EVERY_S:
            looked = time.monotonic()
            try:
                said = changes(said)
            except (OSError, hw.Stop, ValueError) as exc:  # a repo git can't read now: said, and tried next minute
                log(f"changed repos not read: {exc}")
        if time.monotonic() - drifted >= DRIFT_EVERY_S:
            drifted = time.monotonic()
            try:
                said_drift, said_drift_at = drift(said_drift, said_drift_at)
            except (OSError, ValueError) as exc:  # a list hiro-work can't read (ListError is one): said, tried later
                log(f"copy lists not compared: {exc}")
        try:
            key = ship.KEY_FILE.read_text(encoding="utf-8").strip()
            for ask in fetch(key):
                run(ask)
            if down:
                log("CodeHiro answers again")
                down = False
        except (OSError, urllib.error.URLError, ValueError) as exc:
            if not down:
                log(f"CodeHiro can't be asked now: {exc}")
                down = True
        time.sleep(EVERY_S)


def install() -> None:
    """A Startup shortcut for this Windows user (a logon task needs an administrator), and the helper started now."""
    quiet = Path(sys.executable).with_name("pythonw.exe")
    python = quiet if quiet.exists() else Path(sys.executable)
    me = Path(__file__).resolve()
    q = lambda v: "'" + str(v).replace("'", "''") + "'"  # noqa: E731 - a PowerShell single-quoted string
    script = (f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut({q(SHORTCUT)}); $s.TargetPath = {q(python)}; "
              f"$s.Arguments = {q(f'"{me}"')}; $s.WorkingDirectory = {q(me.parent)}; "
              f"$s.Description = {q(NAME)}; $s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-Command", script], check=True, capture_output=True, text=True)
    subprocess.Popen([str(python), str(me)], cwd=me.parent,
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0))
    print(f"'{NAME}': {SHORTCUT} starts it at logon, and it runs now. Its log: {LOG}")


def uninstall() -> None:
    SHORTCUT.unlink(missing_ok=True)
    if PID.exists() and PID.read_text(encoding="utf-8").strip().isdigit():
        subprocess.run(["taskkill", "/PID", PID.read_text(encoding="utf-8").strip(), "/F"], capture_output=True)
        PID.unlink(missing_ok=True)
    print(f"'{NAME}' removed and stopped.")


def main(argv: list[str]) -> int:
    if argv[:1] == ["--install"]:
        install()
        return 0
    if argv[:1] == ["--uninstall"]:
        uninstall()
        return 0
    if argv:
        print(__doc__)
        return 2
    return serve()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
