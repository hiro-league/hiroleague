"""Upgrading an installed app (Installing apps, phase 5; the design's §6, "Upgrade"): a job of the core, as itself.

No admin step: the core changes its own folder of the app and starts and stops its service with the right the
install gave it. The steps, each recorded on the install's row before it is taken (``upgrading``):

1. **Unpacking:** the new release beside the current one (the install's unpack). Same key, a newer version, the same
   program, a core it accepts; the port stays the install's.
2. **Trying its migrations:** the old release's ``predeploy snapshot`` copies the data, then the new release's
   ``predeploy trial`` runs its migrations on a copy (``ALLOW_ROW_LOSS`` = the tables the owner names). A failed trial
   deletes the new release; the app never stopped.
3. **Switching:** the service stops, the data is copied again (what the app wrote meanwhile is kept), ``current``
   points at the new release, the service starts.
4. **Checking its health:** the new version must answer the manifest's ``health`` path with its own version within
   the trial's time plus a margin. Then ``predeploy settled``, and the oldest releases beyond three go.
5. **Going back** (no answer): the service stops, the data is put back from the copy taken at the stop (old release's
   ``predeploy restore``), ``current`` points at the old release, the service starts.

A core that restarts in the middle goes on at its start (:func:`resume`): before the switch it drops the new
release; from the switch on it goes back. Going back can be repeated from any recorded step; one that fails leaves
the install ``failed`` with its words, never a loop.

``predeploy`` and ``health`` come from each release's own manifest (kept in its folder), so the old release puts
its own data back even when the new one can't start.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx
from hiro_channel_sdk.manifest import MANIFEST_FILE, Manifest, ManifestError, parse_manifest
from hiro_commons.log import Logger
from hiro_commons.logging_foundation import story

from .. import __version__
from ..domain import approvals, installs
from ..domain.config import load_config
from ..domain.hiro_home import AppFolder, app_folder
from ..domain.install_consent import sheet
from ..domain.packages import (
    BAD_MANIFEST,
    CORE_VERSION,
    NAME_TAKEN,
    PackageRefused,
    drop_package,
    open_package,
    stored_package,
    version_in,
    version_numbers,
)
from . import app_install

log = Logger.get("EXTENSIONS.UPGRADE")

UNPACKING = "unpacking the new release"
TRYING = "trying its migrations on a copy"
SWITCHING = "switching to the new release"
CHECKING = "checking the new version answers"
GOING_BACK = "going back to the version before"
BEFORE_THE_SWITCH = (UNPACKING, TRYING)
# The steps a page shows, in order (going back is the exception, not a step)
STEPS_IN_ORDER = (UNPACKING, TRYING, SWITCHING, CHECKING)

KEEP_RELEASES = 3
HEALTH_MARGIN_S = 90.0
_PREDEPLOY = re.compile(r"python -m ([A-Za-z_][A-Za-z0-9_.]*)")
_PREDEPLOY_TIMEOUT_S = 1800


class UpgradeFailed(RuntimeError):
    """An upgrade that couldn't go on; the message is for people."""


@dataclass
class Outcome:
    """Where an upgrade ended: ``upgraded``, ``stayed`` (it never switched, or went back) or ``failed``."""

    key: str
    title: str
    before: str
    to: str
    outcome: str
    words: str
    new_asks: list[str] = field(default_factory=list)  # what the new version asks beyond what is approved: it waits


# ---------------------------------------------------------------------------
# Pure rules
# ---------------------------------------------------------------------------


def newer(version: str, than: str) -> bool:
    return version_numbers(version) > version_numbers(than)


def stamp(now: datetime | None = None) -> str:
    """A copy's name for the kit's predeploy: ``pre-deploy-<time>``, which sorts by when it was made (it keeps 5)."""
    return "pre-deploy-" + (now or datetime.now(UTC)).strftime("%Y%m%dT%H%M%S%fZ")


def predeploy_module(manifest: Manifest) -> str | None:
    """The module the manifest's predeploy runs (``python -m hello.predeploy`` → ``hello.predeploy``); None without."""
    if not manifest.predeploy:
        return None
    match = _PREDEPLOY.fullmatch(manifest.predeploy.strip())
    if not match:
        raise UpgradeFailed(f"Its predeploy {manifest.predeploy!r} isn't “python -m <module>”: the core runs nothing "
                            "else.")
    return match[1]


def migrations_seconds(output: str) -> float:
    found = re.findall(r"migrations-seconds=(\d+(?:\.\d+)?)", output)
    return float(found[-1]) if found else 0.0


def summary(output: str) -> str:
    """A step's output in a line for people: its first line and, when there are more, its last (an error's own)."""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        return ""
    first, last = lines[0].rstrip(":"), lines[-1]
    return first if len(lines) == 1 else f"{first}: {last}"


def releases_to_prune(versions: list[str], keep: set[str], newest: int = KEEP_RELEASES) -> list[str]:
    """The releases to delete: all but the newest ``newest`` by version, never one in ``keep`` (current, previous)."""
    ordered = sorted(versions, key=version_numbers, reverse=True)
    return [v for v in ordered[newest:] if v not in keep]


def check_upgrade(row: installs.Install, manifest: Manifest) -> None:
    """PackageRefused when this package can't upgrade this install."""
    if manifest.key != row.key:
        raise PackageRefused(NAME_TAKEN, f"This package is “{manifest.key}”, not “{row.key}”.")
    if row.state == installs.UPGRADING:
        raise PackageRefused(BAD_MANIFEST, f"{row.title} is upgrading already ({row.step}).")
    if row.state != installs.RUNNING:
        raise PackageRefused(BAD_MANIFEST, f"{row.title} isn't running as installed ({row.state}): remove it and "
                                           "install it again.")
    if not newer(manifest.version, row.version):
        raise PackageRefused(BAD_MANIFEST, f"{row.title} is {row.version}: an upgrade goes to a newer version, and "
                                           f"this package is {manifest.version}.")
    if manifest.command != row.command:
        # Its service names the program (written by the admin step): a new one needs installing again
        raise PackageRefused(BAD_MANIFEST, f"{manifest.title} {manifest.version} runs “{manifest.command}”, not "
                                           f"“{row.command}”: remove it and install it again.")
    if not version_in(manifest.core, __version__):
        raise PackageRefused(CORE_VERSION, f"{manifest.title} {manifest.version} works with the core {manifest.core}; "
                                           f"this core is {__version__}.")


# ---------------------------------------------------------------------------
# The steps' parts
# ---------------------------------------------------------------------------


def python_of(release: Path) -> Path:
    return release / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def release_manifest(release: Path) -> Manifest | None:
    try:
        return parse_manifest((release / MANIFEST_FILE).read_text(encoding="utf-8"))
    except (OSError, ManifestError):
        return None


def run_predeploy(release: Path, manifest: Manifest, folder: AppFolder, step: str, copy: str,
                  allowed: list[str] | None = None) -> str:
    """One predeploy step from ``release``, as the core's account, on the app's data; its output, or UpgradeFailed
    with its words."""
    module = predeploy_module(manifest)
    if module is None:
        return "migrations-seconds=0"
    env = {**os.environ, "DATA_DIR": str(folder.data), "ALLOW_ROW_LOSS": ",".join(allowed or [])}
    env.pop("VIRTUAL_ENV", None)
    try:
        done = subprocess.run(  # noqa: S603 — the release's own Python and module, a fixed step
            [str(python_of(release)), "-m", module, step, copy], capture_output=True, text=True, env=env,
            cwd=str(folder.data), timeout=_PREDEPLOY_TIMEOUT_S, check=False, encoding="utf-8", errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise UpgradeFailed(f"Its {step} step couldn't run: {exc}.") from exc
    said = (done.stdout + "\n" + done.stderr).strip()
    if done.returncode != 0:
        # Words for people: the step's first and last lines (a migration's error is its last); the rest is logged
        log.warning(f"⚠️ Upgrade: {folder.key}'s {step} step failed", key=folder.key, step=step, output=said[-3000:])
        raise UpgradeFailed(f"Its {step} step failed: {summary(said) or f'exit code {done.returncode}'}.")
    log.info(f"Upgrade: {step} — {said.splitlines()[0] if said else 'done'}", key=folder.key, step=step)
    return said


def answers(port: int, health: str, version: str, within_s: float) -> bool:
    """Whether the app answers its health path with ``version`` within ``within_s`` (an old process still listening
    answers with its own version, which isn't the new one's)."""
    deadline = time.monotonic() + within_s
    url = f"http://127.0.0.1:{port}{health}"
    with httpx.Client(timeout=5.0) as client:
        while time.monotonic() < deadline:
            if _answered(client, url) == version:
                return True
            time.sleep(1.0)
    return False


def _answered(client: httpx.Client, url: str) -> str | None:
    """The version the app's health path answers, or None while it doesn't answer (not up yet: asked again)."""
    try:
        response = client.get(url)
        return str(response.json().get("version") or "") if response.status_code == 200 else None
    except (httpx.HTTPError, ValueError) as exc:
        log.debug("Upgrade: no answer yet", url=url, error=type(exc).__name__)
        return None


def _stop(service: str) -> None:
    from .. import app_system

    if app_system.is_running(service):
        app_system.stop(service)


def _points_at(folder: AppFolder, release: Path) -> bool:
    return os.path.lexists(folder.current) and Path(os.path.realpath(folder.current)) == Path(os.path.realpath(release))


def new_asks(workspace_path: Path, row: installs.Install, manifest: Manifest, before: Manifest | None) -> list[str]:
    """What the new version asks to do on its own that the version before didn't ask and isn't approved, in words:
    it waits on the Extensions page (Permissions phase 8: a new version that asks for more waits for the owner).
    Fix: an optional ask the owner left off at install was listed as asked for more at every upgrade (seen on the
    PC, Nov 26, 2026)."""
    record = app_install.paired_id(workspace_path, row.key)
    approval = approvals.read(workspace_path, record) if record else None
    approved = approval.approved if approval else []
    domain, port = load_config(workspace_path).site_domain(), row.port or 0
    asked_before = {a.key for a in sheet(before, domain, port)} if before is not None else set()
    return [a.words for a in sheet(manifest, domain, port)
            if a.understood and a.permission not in approvals.IDENTITY and a.key not in asked_before
            and not approvals.covers(approved, a.permission, a.subject)]


# ---------------------------------------------------------------------------
# The job
# ---------------------------------------------------------------------------


def upgrade(workspace_path: Path, key: str, package_id: str, allowed: list[str] | None = None) -> Outcome:
    """Upgrade an installed app to the stored package. Its story is the caller's (``core.extension_upgrade``)."""
    from .. import app_system

    row = installs.get_install(workspace_path, key)
    if row is None:
        raise PackageRefused(NAME_TAKEN, f"“{key}” isn't installed by the core.")
    package = open_package(stored_package(workspace_path, package_id))
    manifest = package.manifest
    check_upgrade(row, manifest)
    folder = app_folder(key, Path(row.home))
    old = folder.release(row.version)
    old_manifest = release_manifest(old) or manifest
    asks = new_asks(workspace_path, row, manifest, release_manifest(old))
    result = Outcome(key, row.title, row.version, manifest.version, "", "", asks)
    story.retitle(f"{row.title} {row.version} → {manifest.version}")
    first = stamp()

    installs.set_upgrade(workspace_path, key, step=UNPACKING, to=manifest.version, stamp=first)
    try:
        new = app_install.unpack(package, folder, workspace_path)
        installs.set_upgrade(workspace_path, key, step=TRYING)
        run_predeploy(old, old_manifest, folder, "snapshot", first)
        tried = run_predeploy(new, manifest, folder, "trial", first, allowed)
    except (app_install.InstallFailed, UpgradeFailed, OSError) as exc:
        _drop_release(folder, manifest.version, keep=row.version)
        installs.end_upgrade(workspace_path, key)
        words = f"{row.title} stays on {row.version}: {exc}"
        story.retitle(f"{row.title} stays on {row.version}: its migration failed" if "trial" in str(exc)
                      else f"{row.title} stays on {row.version}")
        log.warning(f"⚠️ Upgrade refused — {words}", key=key, to=manifest.version)
        result.outcome, result.words = "stayed", words
        return result

    try:
        installs.set_upgrade(workspace_path, key, step=SWITCHING)
        _stop(row.service)
        at_stop = stamp()
        run_predeploy(old, old_manifest, folder, "snapshot", at_stop)  # what it wrote since the first copy
        installs.set_upgrade(workspace_path, key, step=SWITCHING, stamp=at_stop)
        app_install.point_current(folder, new)
        installs.set_upgrade(workspace_path, key, step=CHECKING)
        app_system.start(row.service)
        healthy = answers(row.port or 0, manifest.health, manifest.version,
                          migrations_seconds(tried) + HEALTH_MARGIN_S)
    except (UpgradeFailed, OSError, app_system.ServiceError) as exc:
        log.warning(f"⚠️ Upgrade: switching {row.title} to {manifest.version} failed: {exc}", key=key)
        healthy = False

    if not healthy:
        words = go_back(workspace_path, key)
        result.outcome = "failed" if words.startswith("failed") else "stayed"
        result.words = words.removeprefix("failed: ")
        return result

    try:
        run_predeploy(new, manifest, folder, "settled", installs.get_install(workspace_path, key).upgrade_stamp)
    except UpgradeFailed as exc:  # tidying after a good upgrade: said, never undone for it
        log.warning(f"⚠️ Upgrade: {row.title}'s settled step failed: {exc}", key=key)
    installs.end_upgrade(workspace_path, key, version=manifest.version, previous=row.version)
    prune(folder, current=manifest.version, previous=row.version)
    drop_package(workspace_path, package_id)
    log.info(f"✅ App upgraded — {row.title} {row.version} → {manifest.version}", key=key)
    result.outcome, result.words = "upgraded", f"{row.title} runs {manifest.version}."
    return result


def go_back(workspace_path: Path, key: str) -> str:
    """Back to the version before: stop, put the data back if the new release ran, point at the old release, start.
    Safe to repeat from any recorded step. Returns the words; "failed: ..." when it couldn't."""
    from .. import app_system

    row = installs.get_install(workspace_path, key)
    if row is None:
        return "failed: the install is gone"
    folder = app_folder(key, Path(row.home))
    old, new = folder.release(row.version), folder.release(row.upgrade_to)
    # A release from before releases kept their manifest: the new one names the same app's predeploy module
    old_manifest = release_manifest(old) or release_manifest(new)
    installs.set_upgrade(workspace_path, key, step=GOING_BACK)
    try:
        _stop(row.service)
        if _points_at(folder, new) and old_manifest is not None:
            # Only the new release can have changed the data: before it ran, the data is as the old one left it
            run_predeploy(old, old_manifest, folder, "restore", row.upgrade_stamp)
            app_install.point_current(folder, old)
        app_system.start(row.service)
    except (UpgradeFailed, OSError, app_system.ServiceError) as exc:
        words = f"{row.title} couldn't go back to {row.version}: {exc} Remove it, then install it again."
        installs.end_upgrade(workspace_path, key, state=installs.FAILED, step=words)
        story.retitle(f"{row.title} couldn't go back to {row.version}")
        log.error(f"❌ Upgrade: going back failed — {words}", key=key)
        return f"failed: {words}"
    _drop_release(folder, row.upgrade_to, keep=row.version)
    installs.end_upgrade(workspace_path, key)
    words = f"{row.title} stays on {row.version}: {row.upgrade_to} didn't answer, so the data and the version before " \
            "were put back."
    story.retitle(f"{row.title} stays on {row.version}: {row.upgrade_to} didn't answer")
    log.warning(f"⚠️ Upgrade went back — {words}", key=key)
    return words


def _drop_release(folder: AppFolder, version: str, *, keep: str) -> None:
    if not version or version == keep:
        return
    release = folder.release(version)
    if release.exists() and not _points_at(folder, release):
        shutil.rmtree(release, ignore_errors=True)


def prune(folder: AppFolder, *, current: str, previous: str) -> list[str]:
    """Delete the releases beyond the newest three, never the current or the previous one."""
    if not folder.releases.is_dir():
        return []
    versions = [p.name for p in folder.releases.iterdir() if p.is_dir()]
    gone = releases_to_prune(versions, {current, previous})
    for version in gone:
        shutil.rmtree(folder.release(version), ignore_errors=True)
    return gone


def resume(workspace_path: Path) -> list[str]:
    """At the core's start: an upgrade a restart cut off goes on. Before the switch, the new release is dropped (the
    app never stopped); from the switch on, it goes back. Returns what it did, per app."""
    done = []
    for row in installs.list_installs(workspace_path):
        if row.state != installs.UPGRADING:
            continue
        if row.step in BEFORE_THE_SWITCH:
            _drop_release(app_folder(row.key, Path(row.home)), row.upgrade_to, keep=row.version)
            installs.end_upgrade(workspace_path, row.key)
            log.warning(f"⚠️ Upgrade cut off by a restart — {row.title} stays on {row.version} (it never stopped)",
                        key=row.key)
            done.append(f"{row.key}: stays on {row.version}")
        else:
            done.append(f"{row.key}: {go_back(workspace_path, row.key)}")
    return done
