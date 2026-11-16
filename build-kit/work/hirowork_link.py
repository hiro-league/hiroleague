r"""The hirowork: link on the PC: CodeHiro's environment cards start and stop servers through it (workflow.md, "See
your change running").

    hirowork:up/<env>[/<server>,<server>...]     hiro-work up <env> [servers]
    hirowork:down/<env>[/<server>,<server>...]   hiro-work down <env> [servers]

Windows runs this file with the link when a page opens one (the browser asks first; "Always allow" for the page's
site makes it one click). Only up and down, an environment 0 to 5 and the names hiro-work knows pass; anything else is
refused and logged. The command runs in a tab of the environment's own window (hiro-envN), so its output shows there.
The log is C:\hiro\logs\hirowork-link.log.

    python hirowork_link.py --install     registers the link for this Windows user (HKCU\Software\Classes\hirowork)
    python hirowork_link.py --uninstall   removes it
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hiro_work as hw  # noqa: E402

LAUNCHER = Path(r"C:\hiro\bin\hiro-work.cmd")
LOG = hw.LOGS / "hirowork-link.log"
LINK = re.compile(r"^hirowork:/{0,2}(up|down)/([0-5])(?:/([A-Za-z0-9,_-]+))?/?$")
KEY = r"Software\Classes\hirowork"


class Refused(Exception):
    pass


def parse(link: str) -> tuple[str, int, list[str]]:
    """The command a link asks for: (verb, env, servers). Anything but a known up or down is refused."""
    m = LINK.match(link.strip())
    if not m:
        raise Refused(f"not a hirowork link this handler runs: {link!r}")
    verb, env, names = m.group(1), int(m.group(2)), [n for n in (m.group(3) or "").split(",") if n]
    known = set(hw.servers(env)) | set(hw.SERVED) | {"core"} | set(hw.PORT_ALIASES)
    unknown = [n for n in names if n not in known]
    if unknown:
        raise Refused(f"no server {', '.join(unknown)} in env{env}")
    return verb, env, names


def log(line: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat(timespec='seconds')} {line}\n")


def run(link: str) -> int:
    try:
        verb, env, names = parse(link)
    except Refused as exc:
        log(f"refused: {exc}")
        return 1
    log(f"runs: hiro-work {verb} {env} {' '.join(names)}".rstrip())
    title = f"hiro-work {verb}" + (f" {','.join(names)}" if names else "")
    # A tab of the environment's own window: the command's output stays there a minute, then the tab closes
    wt = [shutil.which("wt.exe") or "wt.exe", "-w", f"hiro-env{env}", "new-tab", "--title", title, "cmd", "/c",
          str(LAUNCHER), verb, str(env), *names, "&", "timeout", "/t", "60"]
    subprocess.Popen(wt, creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    return 0


def install() -> None:
    """Register hirowork: for this Windows user, run by the Python that runs this file."""
    import winreg

    python = Path(sys.executable)
    quiet = python.with_name("pythonw.exe")  # no console window for the handler itself
    command = f'"{quiet if quiet.exists() else python}" "{Path(__file__).resolve()}" "%1"'
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, KEY) as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "URL:Hiro League work")
        winreg.SetValueEx(k, "URL Protocol", 0, winreg.REG_SZ, "")
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, KEY + r"\shell\open\command") as k:
        winreg.SetValueEx(k, "", 0, winreg.REG_SZ, command)
    print(f"hirowork: links now run {command}")


def uninstall() -> None:
    import winreg

    for sub in (r"\shell\open\command", r"\shell\open", r"\shell", ""):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, KEY + sub)
        except FileNotFoundError:
            pass
    print("hirowork: links removed")


def main(argv: list[str]) -> int:
    if argv[:1] == ["--install"]:
        install()
        return 0
    if argv[:1] == ["--uninstall"]:
        uninstall()
        return 0
    if len(argv) != 1:
        print(__doc__)
        return 2
    return run(argv[0])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
