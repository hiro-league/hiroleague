"""Install Hiro League fresh on a throwaway machine, along a person's whole path, and write one result.

    uv run --project hiroserver python build-kit/fresh-install/fresh.py linux [--keep]
    uv run --project hiroserver python build-kit/fresh-install/fresh.py windows [--keep]
    uv run --project hiroserver python build-kit/fresh-install/fresh.py simone [--distro <name>|all] [--keep]

Run from the root of a hiroleague checkout. Everything lands in ``C:\\hiro\\test-packages\\fresh`` (``--root``):

1. **The bundle, as it ships** (``runs/<time>/bundle``): the core's committed code at this checkout's HEAD (``git
   archive``, nothing uncommitted) with the admin pages this checkout built, Hello's test wheels (0.1.0, and 0.1.1 to
   0.1.3 for the three upgrade paths) with the kits' wheels beside them, and the two run scripts. The same bundle a
   person unzips (the clean laptop's hiro-clean-pc.zip).
2. **A fresh machine:**
   - ``linux``: a new WSL distro of Ubuntu 24.04 (Simone's release) with systemd, imported from a pristine image kept
     in ``ubuntu-24.04.tar`` (downloaded once by ``wsl --install``), a person with sudo, then removed (``--keep``
     keeps it: ``wsl -d <its name>``). Needs nothing of an administrator.
   - ``windows``: a new Windows Sandbox (``fresh.wsb``: the bundle mapped read-only, the results folder writable,
     run-windows.ps1 at logon). It closes itself at the end (``--keep`` leaves it open). Needs the Sandbox switched
     on once (an administrator, then a restart).
   - ``simone``: a new virtual machine on Simone per distribution (simone-vm.sh: libvirt, the distribution's official
     cloud image, a person with sudo, 2 CPUs and 4 GB on libvirt's NAT network), deleted after the run; Simone then
     asks for the core's name, as another machine. Ubuntu 24.04 and 22.04, Debian 13, Fedora 45, Rocky 10 (``--distro
     all``: one after another). Needs Michel's account's libvirt group, no sudo; it touches only machines and volumes
     named ``hiro-fresh-*``.
3. **The result:** ``runs/<time>/results/result.md`` (simone: ``runs/<time>/<distro>/results``; one table: each
   step, PASS or FAIL, its time, its log) and ``result.json``. The run script inside the machine walks the path:
   uv, the core, ``hiro service install``, Hello's install, 0.1.3 (goes back), 0.1.2 (stays), 0.1.1 (upgrades), its
   removal, WhatsApp's install, upgrade and removal, the phones' channel refused, the core's LAN name, the service's
   log read for problems.

**The package cache** (the default; ``--fresh`` skips it): every file uv downloads (PyPI's packages, its Pythons)
comes through a cache on Simone (cache-start.sh: proxpi for PyPI, python_mirror.py for the Pythons, kept in
``~/hiro-fresh/cache``), which downloads each file once and serves it from disk after. uv still picks every version
(a list of versions older than 30 minutes is asked again), so a build that changes one package downloads that one.
The only difference from a person's machine: uv's machine-wide settings file points at the cache.

Nothing here touches this PC's or Simone's own Hiro League: no service, no uv tool, no workspace; the machine is
thrown away.
"""

from __future__ import annotations

import argparse
import io
import json
import shutil
import subprocess
import sys
import tarfile
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
ADMIN_PAGES = Path("hiroserver/hirocli/src/hirocli/admin_svelte/static")
DEFAULT_ROOT = Path(r"C:\hiro\test-packages\fresh")
UBUNTU = "Ubuntu-24.04"
PERSON = "person"
# Inside the Sandbox: where the bundle and the results are mapped
SANDBOX_BUNDLE = r"C:\fresh\bundle"
SANDBOX_RESULTS = r"C:\fresh\results"
_WAIT_S = 3 * 3600  # a first run downloads uv, Python, every package, WinSW and Caddy
# The package cache on Simone (cache-start.sh): every machine reaches it at Simone's LAN address (the VMs too, through
# their NAT network)
CACHE_HOST = "192.168.1.10"
CACHE_INDEX = f"http://{CACHE_HOST}:3141/index/"
CACHE_PYTHONS = f"http://{CACHE_HOST}:3142"


def say(text: str) -> None:
    print(text, flush=True)


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kw)


# --- the bundle ----------------------------------------------------------------------------------------------------


def start_cache() -> None:
    """Start the package cache on Simone when it isn't running (cache-start.sh): PyPI and uv's Pythons."""
    run(["ssh", SIMONE, "mkdir -p hiro-fresh"])
    run(["scp", "-q", str(HERE / "cache-start.sh"), str(HERE / "python_mirror.py"), f"{SIMONE}:hiro-fresh/"])
    run(["ssh", SIMONE, "bash hiro-fresh/cache-start.sh"])


def build_bundle(out: Path, *, close: bool, cache: bool) -> str:
    """The bundle as it ships; returns the commit it holds."""
    commit = run(["git", "-C", str(REPO), "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = run(["git", "-C", str(REPO), "status", "--porcelain", "--untracked-files=no"], capture_output=True,
                text=True).stdout.strip()
    if dirty:
        say(f"Note: this checkout has uncommitted changes; the bundle holds the commit {commit} only.")
    pages = REPO / ADMIN_PAGES
    if not (pages / "index.html").is_file():
        raise SystemExit(f"The admin pages aren't built here ({pages}): npm --prefix admin_frontend run package:python")
    say(f"Bundle: the core at {commit}, its admin pages, Hello's wheels → {out}")
    archive = run(["git", "-C", str(REPO), "archive", "--format=tar", "HEAD"], capture_output=True).stdout
    core = out / "hiroleague"
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(core, filter="data")
    shutil.copytree(pages, core / ADMIN_PAGES, dirs_exist_ok=True)
    hello = out / "hello"
    python = sys.executable
    run([python, str(REPO / "build-kit" / "package.py"), str(REPO / "build-kit" / "test-app"), "--out", str(hello),
         "--ui-built"], cwd=REPO)
    run([python, str(REPO / "build-kit" / "test-app" / "variants.py"), "--out", str(hello)], cwd=REPO)
    for script in ("run-linux.sh", "run-windows.ps1", "read_logs.py"):
        shutil.copy2(HERE / script, out / script)
    (out / "COMMIT").write_text(commit + "\n", encoding="utf-8")
    if close:
        (out / "CLOSE").write_text("close the machine when the run ends\n", encoding="utf-8")
    if cache:  # the run scripts point the machine's uv at the cache (--fresh: no file, the internet as a person's)
        (out / "CACHE").write_text(f"{CACHE_INDEX} {CACHE_PYTHONS}\n", encoding="utf-8")
    return commit


# --- Windows Sandbox -----------------------------------------------------------------------------------------------


def wsb(bundle: Path, results: Path) -> str:
    """The Sandbox's configuration: the bundle read-only, the results writable, the run script at logon."""
    command = (f"powershell.exe -NoProfile -ExecutionPolicy Bypass -File {SANDBOX_BUNDLE}\\run-windows.ps1 "
               f"-Bundle {SANDBOX_BUNDLE} -Results {SANDBOX_RESULTS}")
    return f"""<Configuration>
  <Networking>Enable</Networking>
  <MemoryInMB>8192</MemoryInMB>
  <MappedFolders>
    <MappedFolder>
      <HostFolder>{bundle}</HostFolder>
      <SandboxFolder>{SANDBOX_BUNDLE}</SandboxFolder>
      <ReadOnly>true</ReadOnly>
    </MappedFolder>
    <MappedFolder>
      <HostFolder>{results}</HostFolder>
      <SandboxFolder>{SANDBOX_RESULTS}</SandboxFolder>
      <ReadOnly>false</ReadOnly>
    </MappedFolder>
  </MappedFolders>
  <LogonCommand>
    <Command>{command}</Command>
  </LogonCommand>
</Configuration>
"""


def run_windows(run_dir: Path, bundle: Path, results: Path) -> None:
    sandbox = shutil.which("WindowsSandbox.exe") or r"C:\Windows\System32\WindowsSandbox.exe"
    if not Path(sandbox).is_file():
        raise SystemExit("Windows Sandbox isn't switched on. In an administrator PowerShell: Enable-WindowsOptionalFeature "
                         "-Online -FeatureName Containers-DisposableClientVM -All, then restart.")
    config = run_dir / "fresh.wsb"
    config.write_text(wsb(bundle, results), encoding="utf-8")
    say(f"Windows Sandbox: {config}")
    subprocess.Popen([sandbox, str(config)])
    wait_for(results)


# --- WSL -----------------------------------------------------------------------------------------------------------


def wsl(*args: str, **kw) -> subprocess.CompletedProcess:
    return run(["wsl.exe", *args], **kw)


def pristine_image(root: Path) -> Path:
    """Ubuntu 24.04 as it comes, exported once: each run imports a new distro from it."""
    image = root / "ubuntu-24.04.tar"
    if image.is_file():
        return image
    name = "hiro-fresh-image"
    say(f"First run: downloading {UBUNTU} once → {image}")
    wsl("--install", UBUNTU, "--name", name, "--location", str(root / "image-distro"), "--no-launch")
    try:
        wsl("--export", name, str(image))
    finally:
        subprocess.run(["wsl.exe", "--unregister", name], check=False)
    return image


def to_linux(path: Path) -> str:
    """A Windows path as WSL mounts it: C:\\a\\b → /mnt/c/a/b."""
    return "/mnt/" + path.drive[0].lower() + path.as_posix()[2:]


SETUP = f"""set -e
useradd -m -s /bin/bash -G sudo {PERSON}
echo '{PERSON} ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/{PERSON}
# No Windows programs and no Windows PATH inside: a fresh machine has neither
printf '[boot]\\nsystemd=true\\n[user]\\ndefault={PERSON}\\n[interop]\\nenabled=false\\nappendWindowsPath=false\\n' > /etc/wsl.conf
"""


def run_linux(root: Path, run_dir: Path, bundle: Path, results: Path, *, keep: bool) -> None:
    image = pristine_image(root)
    name = f"hiro-fresh-{run_dir.name}"
    wsl("--import", name, str(run_dir / "distro"), str(image))
    try:
        wsl("-d", name, "-u", "root", "--", "bash", "-c", SETUP)
        wsl("--terminate", name)  # the next start has systemd and the person
        home_bundle = f"/home/{PERSON}/hiro-test"
        wsl("-d", name, "-u", PERSON, "--", "cp", "-r", to_linux(bundle), home_bundle)
        say(f"WSL {name}: the person's path (its output below)")
        subprocess.run(["wsl.exe", "-d", name, "-u", PERSON, "--cd", "~", "--", "bash",
                        f"{home_bundle}/run-linux.sh", home_bundle, to_linux(results)], check=False)
    finally:
        if keep:
            say(f"Kept: wsl -d {name}   (remove it: wsl --unregister {name})")
        else:
            subprocess.run(["wsl.exe", "--unregister", name], check=False)
    if not (results / "finished").is_file():
        raise SystemExit(f"The run script stopped before its result: see its output above and {results / 'logs'}")


# --- Simone: a throwaway virtual machine per distribution ---------------------------------------------------------

SIMONE = "simone"  # the server, as ssh names it
DISTROS = ("ubuntu-24.04", "ubuntu-22.04", "debian-13", "fedora-45", "rocky-10")


def run_simone(run_dir: Path, bundle: Path, distro: str, *, keep: bool) -> Path:
    """One throwaway machine on Simone (simone-vm.sh: libvirt, the distribution's cloud image); returns its results."""
    name = f"{run_dir.name}-{distro}"
    remote = f"hiro-fresh/runs/{name}"
    local = run_dir / distro
    local.mkdir(parents=True)
    tar = run_dir / "bundle.tar"
    if not tar.is_file():
        with tarfile.open(tar, "w") as out:
            out.add(bundle, arcname=".")
    run(["ssh", SIMONE, f"mkdir -p {remote}"])
    run(["scp", "-q", str(tar), str(HERE / "simone-vm.sh"), f"{SIMONE}:{remote}/"])
    say(f"Simone: {distro} in a throwaway machine (its output below)")
    subprocess.run(["ssh", SIMONE, "bash", f"{remote}/simone-vm.sh", distro, name, *(["--keep"] if keep else [])],
                   check=False)
    subprocess.run(["scp", "-q", "-r", f"{SIMONE}:{remote}/results", str(local)], check=False)
    return local / "results"


# --- the result ----------------------------------------------------------------------------------------------------


def wait_for(results: Path, timeout_s: int = _WAIT_S) -> None:
    deadline = time.monotonic() + timeout_s
    while not (results / "finished").is_file():
        if time.monotonic() > deadline:
            raise SystemExit(f"No result after {timeout_s // 60} min: see {results / 'logs'}")
        time.sleep(10)


def report(results: Path) -> bool:
    """Print one machine's result; True when every step passed."""
    result, summary = results / "result.md", results / "result.json"
    if not (result.is_file() and summary.is_file()):
        say(f"The run wrote no result: see {results / 'logs'}")
        return False
    say(result.read_text(encoding="utf-8"))
    say(f"Result: {result}")
    return bool(json.loads(summary.read_text(encoding="utf-8")).get("passed"))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Install Hiro League fresh on a throwaway machine.")
    parser.add_argument("system", choices=("linux", "windows", "simone"))
    parser.add_argument("--distro", choices=(*DISTROS, "all"), default=DISTROS[0],
                        help=f"simone: the distribution, or all of them one after another (default {DISTROS[0]})")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help=f"where runs go (default {DEFAULT_ROOT})")
    parser.add_argument("--keep", action="store_true", help="keep the machine after the run, to look inside")
    parser.add_argument("--fresh", action="store_true",
                        help="download everything from the internet, as a person's first install (default: through "
                             "the package cache on Simone, which downloads each file once)")
    args = parser.parse_args(argv)
    run_dir = args.root / "runs" / f"{datetime.now().astimezone():%Y%m%d-%H%M%S}-{args.system}"  # this PC's time
    bundle, results = run_dir / "bundle", run_dir / "results"
    results.mkdir(parents=True)
    if not args.fresh:
        start_cache()
    build_bundle(bundle, close=not args.keep, cache=not args.fresh)
    if args.system == "simone":
        distros = DISTROS if args.distro == "all" else (args.distro,)
        passed = {d: report(run_simone(run_dir, bundle, d, keep=args.keep)) for d in distros}
        if len(passed) > 1:
            say("\n".join(f"{'PASS' if ok else 'FAIL'}  {d}" for d, ok in passed.items()))
        return 0 if all(passed.values()) else 1
    if args.system == "windows":
        run_windows(run_dir, bundle, results)
    else:
        run_linux(args.root, run_dir, bundle, results, keep=args.keep)
    return 0 if report(results) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
