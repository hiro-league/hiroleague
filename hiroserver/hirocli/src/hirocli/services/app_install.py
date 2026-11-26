"""Installing and removing an app: the core's own steps (Installing apps, phase 5; the design's §8).

One install is three steps, the middle one a person's:

1. **The sheet and the yes** (the core, as itself): the package handed to it (domain/packages.py's store) is read and
   checked (its key, its name free, the core's version, its port), and the person is shown what the app asks in the
   Extensions page's words (domain/install_consent.py). Their yes is kept on a new ``installs`` row (``approving``),
   with the job for the system part.
2. **The admin step** (``hiro extension system <job>``, sudo or Windows' prompt): the app's account, folder and
   service, and the core's right to start and stop it (app_system.py). Never here.
3. **The finish** (the core, as itself, in the running core: on Windows only it holds the right on the service): the
   release is unpacked into ``releases/<version>`` (a uv venv, the package's pinned requirements with their hashes,
   its wheels), ``current`` points at it, the app's environment is written with a new pairing code, and the service
   starts. The row is ``waiting`` until the app pairs with that code (runtime/extension_manager.py), then ``running``.

A step after the admin step that fails leaves the row ``failed`` with its words; removing it still works from any
state. Removing is the admin step first (stop, the service, the right, the account; ``--purge`` the folder), then
:func:`forget` here.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

from hiro_channel_sdk.constants import ENV_CORE_URL, ENV_PAIRING_CODE
from hiro_channel_sdk.manifest import KIND_APP, Manifest
from hiro_commons.log import Logger

from .. import __version__
from ..domain import installs
from ..domain.approvals import Asked
from ..domain.config import Config, load_config
from ..domain.extension_keys import key_refusal
from ..domain.extensions import ExtensionNameTaken, check_name_free, list_paired_extensions
from ..domain.hiro_home import AppFolder, app_folder, hiro_home
from ..domain.install_consent import consent, sheet
from ..domain.packages import (
    BAD_MANIFEST,
    CORE_VERSION,
    NAME_TAKEN,
    PORT_TAKEN,
    Package,
    PackageRefused,
    drop_package,
    open_package,
    service_name,
    stored_package,
    version_in,
)
from ..domain.site_names import list_claims, list_other_sites
from ..domain.system_job import INSTALL, AppSystem, SystemJob, check_job

log = Logger.get("EXTENSIONS.INSTALL")

PYTHON = "3.12"  # every Hiro League backend's Python (the backend guide's stack)
ENV_DATA_DIR = "DATA_DIR"
ENV_PORT = "PORT"
_UV_TIMEOUT_S = 900
_ANY = frozenset({"", "0.0.0.0", "::"})  # noqa: S104 — the names of "every interface", compared, never bound


class InstallFailed(RuntimeError):
    """A step of the install failed; the message is for people (it is also the row's ``step``)."""


@dataclass(frozen=True)
class Sheet:
    """What the person is shown before they approve: the package's app and what it asks."""

    package: Package
    port: int
    items: list[Asked]


# ---------------------------------------------------------------------------
# 1. The sheet and the yes
# ---------------------------------------------------------------------------


def core_ports(config: Config) -> set[int]:
    return {config.http_port, config.admin_port, config.effective_extension_port(), config.gateway_port}


def port_problem(workspace_path: Path, port: int, config: Config) -> str | None:
    """Why ``port`` can't be this app's, in words, or None: another install's, a paired app's name, another site's
    target, the core's own, or something already listening there."""
    if any(i.port == port for i in installs.list_installs(workspace_path)):
        return f"The port {port} is another installed app's."
    if any(c.port == port for c in list_claims(workspace_path)):
        return f"The port {port} is a paired app's: its name on the home network points there."
    if any(s.target.rstrip("/").endswith(f":{port}") for s in list_other_sites(workspace_path)):
        return f"The port {port} is another site's on this machine."
    if port in core_ports(config):
        return f"The port {port} is the core's own."
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return f"Something on this machine already listens on the port {port}."
    return None


def check(workspace_path: Path, manifest: Manifest, config: Config) -> None:
    """PackageRefused when the core won't install this package here, with its code and words."""
    if manifest.kind != KIND_APP:
        raise PackageRefused(BAD_MANIFEST, "Only apps install this way for now; channels come with their own step.")
    refusal = key_refusal(manifest.key)
    if refusal:
        raise PackageRefused(NAME_TAKEN, refusal)
    if installs.get_install(workspace_path, manifest.key) is not None:
        raise PackageRefused(NAME_TAKEN, f"“{manifest.key}” is installed already: remove it first.")
    try:
        check_name_free(workspace_path, manifest.key)
    except ExtensionNameTaken as exc:
        raise PackageRefused(NAME_TAKEN, str(exc)) from exc
    if not version_in(manifest.core, __version__):
        raise PackageRefused(CORE_VERSION, f"{manifest.title} {manifest.version} works with the core {manifest.core}; "
                                           f"this core is {__version__}.")
    assert manifest.port is not None  # noqa: S101 — an app's manifest names its port (Manifest's own check)
    problem = port_problem(workspace_path, manifest.port, config)
    if problem:
        raise PackageRefused(PORT_TAKEN, problem)


def read_sheet(workspace_path: Path, package_id: str) -> Sheet:
    """The stored package, checked, and what its app asks. PackageRefused when it can't be installed here."""
    config = load_config(workspace_path)
    package = open_package(stored_package(workspace_path, package_id))
    drop_stale(workspace_path, package.manifest.key)
    check(workspace_path, package.manifest, config)
    port = package.manifest.port or 0
    return Sheet(package=package, port=port, items=sheet(package.manifest, config.site_domain(), port))


def system_job(manifest: Manifest) -> SystemJob:
    return SystemJob(action=INSTALL, key=manifest.key, command=manifest.command)


APPROVED_WHEN_ASKED = "approved when asked"
APPROVED_IN_ADVANCE = "approved in advance (--approve)"


def prepare(workspace_path: Path, package_id: str, chosen: set[tuple[str, str]] | None, *,
            in_advance: bool = False) -> tuple[installs.Install, SystemJob]:
    """The person said yes: the row (``approving``) with what they approved, how they said it (asked, or in
    advance), and the system part's job. The sheet is read again from the same package, so what is kept is what was
    shown."""
    found = read_sheet(workspace_path, package_id)
    manifest = found.package.manifest
    agreed = consent(found.items, chosen)
    service = service_name(manifest.key)
    try:
        row = installs.add_install(
            workspace_path, key=manifest.key, kind=manifest.kind, title=manifest.title, version=manifest.version,
            port=found.port, service=service, account=service, home=str(hiro_home()), consent=agreed,
            package=package_id, command=manifest.command,
        )
    except installs.InstallExists as exc:
        raise PackageRefused(NAME_TAKEN, str(exc)) from exc
    how = APPROVED_IN_ADVANCE if in_advance else APPROVED_WHEN_ASKED
    installs.set_state(workspace_path, manifest.key, installs.APPROVING, step=how)
    row = installs.get_install(workspace_path, manifest.key) or row
    log.info(f"📦 Install approved — {manifest.title} {manifest.version}: {len(agreed)} item(s), {how}; the admin "
             "step next", key=manifest.key, port=found.port, items=", ".join(_item(i) for i in agreed))
    return row, system_job(manifest)


def drop_stale(workspace_path: Path, key: str) -> bool:
    """Drop an install left ``approving`` with nothing made for it, so it doesn't refuse the next try. Fix: one whose
    CLI was closed before its admin step made anything refused the next try as "installed already" (seen on the PC,
    Nov 26, 2026). One whose service exists is left alone: its install may still be running elsewhere."""
    from .. import app_system

    row = installs.get_install(workspace_path, key)
    if row is None or row.state != installs.APPROVING or app_system.is_running(row.service) is not None:
        return False
    return cancel(workspace_path, key)


def cancel(workspace_path: Path, key: str) -> bool:
    """The install stopped before it finished (its admin step declined or failed, the CLI stopped). Decided by what
    the system has, not by what the CLI heard: with no service made, the row and its package go (nothing outside the
    core was made); once the service exists, the row stays ``failed`` so ``hiro extension remove`` takes it all away.
    Returns whether the row went."""
    from .. import app_system

    row = installs.get_install(workspace_path, key)
    if row is None or row.state != installs.APPROVING:
        return False
    if app_system.is_running(row.service) is not None:
        words = "The install stopped after its account and service were made: remove it, then install it again."
        installs.set_state(workspace_path, key, installs.FAILED, step=words)
        log.warning(f"⚠️ Install stopped partway — {row.title}: its service exists, the row is kept to remove it",
                    key=key, service=row.service)
        return False
    installs.remove_install(workspace_path, key)
    drop_package(workspace_path, row.package)
    log.info(f"Install cancelled — {row.title}: nothing was made", key=key)
    return True


def _item(i: object) -> str:
    permission, subject = getattr(i, "permission", ""), getattr(i, "subject", "")
    return f"{permission}:{subject}" if subject else permission


# ---------------------------------------------------------------------------
# 3. The finish
# ---------------------------------------------------------------------------


def installed_core_url(config: Config) -> str:
    """The core's extension socket as an app on this machine reaches it."""
    host = config.extension_host.strip()
    host = "127.0.0.1" if host in _ANY else host
    return f"ws://{host}:{config.effective_extension_port()}"


def app_environment(folder: AppFolder, port: int, core_url: str, code: str = "") -> dict[str, str]:
    """What the app's service runs with: its data folder, its port, its core, and its pairing code until it paired."""
    env = {ENV_DATA_DIR: str(folder.data), ENV_PORT: str(port), ENV_CORE_URL: core_url}
    if code:
        env[ENV_PAIRING_CODE] = code
    return env


def render_env_file(env: dict[str, str]) -> str:
    """app.env as systemd's EnvironmentFile reads it (and /bin/sh sources it on a Mac): one KEY="value" a line."""
    for value in env.values():
        if any(c in value for c in '"\\\n$`'):
            raise InstallFailed(f"A value of the app's environment can't be written safely: {value!r}.")
    return "".join(f'{k}="{v}"\n' for k, v in env.items())


def _app(row: installs.Install) -> AppSystem:
    return check_job(SystemJob(action=INSTALL, key=row.key, command=row.command), Path(row.home))


def write_environment(workspace_path: Path, row: installs.Install, code: str = "") -> None:
    """Write the app's environment where its service reads it: app.env (Linux, Mac; only the core reads it, systemd
    reads it as root), or its WinSW configuration (Windows: WinSW has no environment file)."""
    from .. import app_system

    app = _app(row)
    env = app_environment(app.folder, row.port or 0, installed_core_url(load_config(workspace_path)), code)
    if sys.platform == "win32":
        app_system.write_windows_environment(app, env)
        return
    path = app.folder.env_file
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_text(render_env_file(env), encoding="utf-8")
        tmp.chmod(0o600)  # it holds the pairing code until the app paired
        tmp.replace(path)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise InstallFailed(f"The app's environment couldn't be written: {exc}.") from exc


def find_uv(home: Path) -> str:
    """uv: on the core's PATH, else the Hiro home's own copy (a service core on Windows has no PATH of the person's;
    the admin step puts uv there)."""
    found = shutil.which("uv") or shutil.which("uv", path=str(home / "bin"))
    if not found:
        raise InstallFailed("uv isn't on this machine (neither on the PATH nor in the Hiro home's bin): install uv, "
                            "then install the app again.")
    return found


def _uv(args: list[str], what: str, env: dict[str, str]) -> None:
    try:
        done = subprocess.run(  # noqa: S603 — uv with fixed arguments and the release's own paths, no shell
            args, capture_output=True, text=True, timeout=_UV_TIMEOUT_S, check=False, env=env, encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InstallFailed(f"{what} failed: {exc}.") from exc
    if done.returncode != 0:
        detail = " | ".join((done.stderr or done.stdout).strip().splitlines()[-3:])
        raise InstallFailed(f"{what} failed: {detail or f'exit code {done.returncode}'}.")


def unpack(package: Package, folder: AppFolder, workspace_path: Path) -> Path:
    """The release ``releases/<version>``: a venv on the Hiro home's Python, the package's pinned requirements (their
    hashes required) and its wheels, without their dependencies (the requirements hold them all). A failed try's
    leftovers are replaced."""
    manifest = package.manifest
    release = folder.release(manifest.version)
    staging = folder.root / ".incoming"
    for path in (release, staging):
        if path.exists():
            shutil.rmtree(path)
    staging.mkdir(parents=True)
    with zipfile.ZipFile(package.path) as zf:  # open_package checked every member stays inside its folder
        for name in (*package.wheels, "requirements.txt"):
            if name in zf.namelist():
                zf.extract(name, staging)
    env = {
        **os.environ,
        "UV_PYTHON_INSTALL_DIR": str(folder.root / "python"),  # the app's own Python, readable by its account
        "UV_CACHE_DIR": str(workspace_path / "cache" / "uv"),
        "UV_LINK_MODE": "copy",  # the release never points into the core's cache
    }
    uv = find_uv(folder.home)
    _uv([uv, "venv", "--managed-python", "--python", PYTHON, "--no-project", str(release)], "Making the app's Python", env)
    if package.requirements.strip():
        _uv([uv, "pip", "install", "--python", str(release), "--require-hashes", "--no-deps",
             "-r", str(staging / "requirements.txt")], "Installing the app's libraries", env)
    _uv([uv, "pip", "install", "--python", str(release), "--no-deps",
         *(str(staging / w) for w in package.wheels)], "Installing the app", env)
    shutil.rmtree(staging)
    return release


def point_current(folder: AppFolder, release: Path) -> None:
    """``current`` points at the release: a symlink, a junction on Windows (no admin needed)."""
    current = folder.current
    tmp = folder.root / ".current-new"
    if os.path.lexists(tmp):
        os.unlink(tmp) if sys.platform != "win32" else os.rmdir(tmp)
    if sys.platform == "win32":
        import _winapi

        _winapi.CreateJunction(str(release), str(tmp))
        if os.path.lexists(current):
            os.rmdir(current)  # a junction: removes the link, never the release it points at
        os.rename(tmp, current)
    else:
        os.symlink(release, tmp, target_is_directory=True)
        os.replace(tmp, current)


def finish(workspace_path: Path, key: str) -> installs.Install:
    """Unpack, write the environment with a new pairing code, start the service: ``waiting``. Only an install whose
    admin step made its service. InstallFailed (the row ``failed``, its step the words) when a step fails."""
    from .. import app_system

    row = installs.get_install(workspace_path, key)
    if row is None or row.state not in (installs.APPROVING, installs.FAILED):
        raise InstallFailed(f"“{key}” isn't an install waiting to finish.")
    if app_system.is_running(row.service) is None:
        raise InstallFailed(f"{row.title}'s service isn't made yet: its admin step didn't run, or was declined.")
    # The person's yes, said in this story: what they approved and how (asked, or in advance with --approve)
    log.info(f"Install: {row.title} {row.version}, {row.step or APPROVED_WHEN_ASKED}: "
             f"{', '.join(_item(i) for i in row.consent) or 'nothing'}", key=key)
    try:
        package = open_package(stored_package(workspace_path, row.package))
        if package.manifest.key != key:  # the row names the package it was approved from
            raise InstallFailed("The stored package isn't the one this install was approved from.")
        app = _app(row)
        installs.set_state(workspace_path, key, installs.APPROVING, step="Unpacking the release")
        release = unpack(package, app.folder, workspace_path)
        point_current(app.folder, release)
        code = installs.new_code()
        installs.set_code(workspace_path, key, code)
        write_environment(workspace_path, row, code)
        app_system.start(row.service)
    except (InstallFailed, PackageRefused, OSError, app_system.ServiceError) as exc:
        words = str(exc)
        installs.set_state(workspace_path, key, installs.FAILED, step=words)
        log.warning(f"⚠️ Install failed — {row.title}: {words}", key=key)
        raise InstallFailed(words) from exc
    drop_package(workspace_path, row.package)
    installs.set_package(workspace_path, key, "")
    installs.set_state(workspace_path, key, installs.WAITING, step="Waiting for the app to pair")
    log.info(f"✅ App installed — {row.title} {row.version}: its service runs, it pairs next", key=key,
             service=row.service, port=row.port)
    done = installs.get_install(workspace_path, key)
    assert done is not None  # noqa: S101 — just written
    return done


def paired(workspace_path: Path, key: str) -> None:
    """The app paired with its install's code: its environment is written again without the code (used once). A
    failure here is said and changes nothing else: the code is dead already (its hash is gone)."""
    row = installs.get_install(workspace_path, key)
    if row is None:
        return
    try:
        write_environment(workspace_path, row)
    except (InstallFailed, OSError) as exc:
        log.warning(f"⚠️ Install: {row.title} paired, but its environment still holds the used code: {exc}", key=key)


# ---------------------------------------------------------------------------
# Removing: after the admin step
# ---------------------------------------------------------------------------


def forget(workspace_path: Path, key: str) -> installs.Install | None:
    """The admin step removed the app's service and account: the core drops its releases, its Python and its
    configuration, the old pairing's key in its data (the record it pairs with is gone, so a later install pairs
    anew), its row and its package. The app's own data stays unless the admin step purged the folder."""
    row = installs.get_install(workspace_path, key)
    if row is None:
        return None
    folder = app_folder(key, Path(row.home))
    if os.path.lexists(folder.current):
        os.unlink(folder.current) if sys.platform != "win32" else os.rmdir(folder.current)
    for path in (folder.releases, folder.root / "python", folder.root / ".incoming", folder.service_dir,
                 folder.data / "hiroleague"):
        if path.exists():
            shutil.rmtree(path, ignore_errors=False)
    folder.env_file.unlink(missing_ok=True)
    installs.remove_install(workspace_path, key)
    drop_package(workspace_path, row.package)
    log.info(f"App's install forgotten — {row.title}", key=key)
    return row


def paired_id(workspace_path: Path, key: str) -> str | None:
    """The paired record of an installed app (the same key as its name), if it paired."""
    return next((e.extension_id for e in list_paired_extensions(workspace_path) if e.name == key), None)
