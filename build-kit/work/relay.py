r"""The PC's helper for CodeHiro's environment cards (workflow.md, "See your change running").

A card's Up or Down goes to CodeHiro (POST /api/work/asks). This helper, running on the PC from logon, asks CodeHiro
every few seconds for what is waiting (GET /api/work/asks/next, with the Work key the sender uses) and runs each ask:

    up <env> [servers]     hiro-work up <env> [servers]
    down <env> [servers]   hiro-work down <env> [servers]

in a tab of the environment's own window (hiro-envN), so its output shows there; the servers' events then reach the
card. Only up and down, an environment 0 to 5 and the server names hiro-work knows pass; anything else is refused and
logged. One helper at a time (C:\hiro\run\relay.pid). Its log is C:\hiro\logs\relay.log. Standard library only.

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
LOG = hw.LOGS / "relay.log"
PID = hw.RUN / "relay.pid"
URL = ship.URL.rsplit("/events", 1)[0] + "/asks/next"  # http://reports.local/api/work/asks/next
EVERY_S = 3
NAME = "Hiro League work relay"
SHORTCUT = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / (
    NAME + ".lnk")


class Refused(Exception):
    pass


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


def run(ask: dict) -> bool:
    try:
        verb, env, names = check(ask)
    except Refused as exc:
        log(f"refused: {exc}")
        return False
    log(f"runs: hiro-work {verb} {env} {' '.join(names)}".rstrip())
    title = f"hiro-work {verb}" + (f" {','.join(names)}" if names else "")
    # A tab of the environment's own window: the command's output stays there a minute, then the tab closes
    wt = [shutil.which("wt.exe") or "wt.exe", "-w", f"hiro-env{env}", "new-tab", "--title", title, "cmd", "/c",
          str(LAUNCHER), verb, str(env), *names, "&", "timeout", "/t", "60"]
    subprocess.Popen(wt, creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    return True


def fetch(key: str) -> list[dict]:
    """What CodeHiro holds for the PC; [] when it can't be reached (said once in the log until it answers again)."""
    req = urllib.request.Request(URL, headers={"X-Work-Key": key})
    with urllib.request.urlopen(req, timeout=10) as r:
        return list(json.loads(r.read().decode("utf-8")).get("asks") or [])


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
    while True:
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
