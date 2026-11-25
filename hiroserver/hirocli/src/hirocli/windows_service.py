"""The Hiro server as a Windows service: what `hiro service install` puts on the system.

The service runs as its own virtual account (``NT SERVICE\\hiro``), which can't read anything under a person's
profile: not uv's Python, not the `hiro` that `uv tool install` put there, not their workspace. So everything the
service runs and keeps lives in one machine-wide folder, the Hiro home (``%ProgramData%\\HiroLeague`` unless the
install names another), the way Simone's deploy uses ``/opt/hiroleague``:

    <home>\\python\\              the Python uv installs (UV_PYTHON_INSTALL_DIR)
    <home>\\releases\\<time>\\    one install of Hiro League (its tools and its bin\\hiro.exe)
    <home>\\service\\<name>.exe   the service's own copy of WinSW, and <name>.xml beside it
    <home>\\<name>.env            the secrets file (provider keys), read by the server itself
    <data>\\                      the workspace registry and workspaces (HIRO_DATA_DIR); <home>\\data unless named
    <data>\\service-logs\\        WinSW's own log and what the server writes before its log file is open

Builds the Hiro-specific parts and hands them to the generic ``hiro_commons.winsw_service``; mirrors
``hirocli.linux_service``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath

from hiro_commons.log import Logger
from hiro_commons.systemd_service import NULL_KEYRING_BACKEND, ServiceError, render_env_file
from hiro_commons.winsw_service import WinswSpec

from .constants import ENV_DATA_DIR, ENV_SECRETS_FILE, ENV_SERVICE_MANAGER
from .linux_service import SERVICE_DESCRIPTION, provider_env_sections, service_name

log = Logger.get("CLI.SERVICE")

PYTHON_VERSION = "3.12"
DATA_FOLDER = "data"
SERVICE_LOGS_FOLDER = "service-logs"
# Where a checkout keeps the admin's built pages, from its uv workspace's root (admin_svelte/static_server.py).
ADMIN_ASSETS = Path("hirocli/src/hirocli/admin_svelte/static")
# uv downloads Python and every package on a first install: minutes on a slow line.
_INSTALL_TIMEOUT_S = 1800


def default_home() -> Path:
    return Path(os.environ.get("ProgramData") or r"C:\ProgramData") / "HiroLeague"


@dataclass(frozen=True)
class Layout:
    """Where one Windows install keeps its parts (the module's docstring)."""

    home: Path
    data_dir: Path

    @property
    def python_dir(self) -> Path:
        return self.home / "python"

    @property
    def releases_dir(self) -> Path:
        return self.home / "releases"

    @property
    def service_dir(self) -> Path:
        return self.home / "service"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / SERVICE_LOGS_FOLDER

    def secrets_file(self, name: str) -> Path:
        return self.home / f"{name}.env"


def layout(home: str | None, data_dir: str | None) -> Layout:
    """The install's folders: the ones named, else the defaults. Both must be absolute."""
    home_path = Path(home).expanduser() if home else default_home()
    data_path = Path(data_dir).expanduser() if data_dir else home_path / DATA_FOLDER
    for label, path in (("--home", home_path), ("--data-dir", data_path)):
        # PureWindowsPath: these are Windows paths, whatever system checks them (the tests run on Linux too).
        if not PureWindowsPath(path).is_absolute():
            raise ServiceError(f"{label} must be a full path, such as D:\\HiroLeague (got '{path}').")
    return Layout(home=home_path, data_dir=data_path)


def installed_package_spec() -> str:
    """What to install for the service when the install names nothing: this same Hiro League.

    Run from a checkout, that is the checkout itself: its version number (0.2.0) also names an older release on PyPI,
    which knows nothing of the service's data folder or secrets file.
    """
    from importlib.metadata import PackageNotFoundError, version

    from hiro_commons.process import find_workspace_root

    root = find_workspace_root(Path(__file__))
    if root is not None and (root / "hiroleague" / "pyproject.toml").is_file():
        return str(root / "hiroleague")
    try:
        return f"hiroleague=={version('hiroleague')}"
    except PackageNotFoundError:
        return f"hiroleague=={version('hirocli')}"


def _system_path(bin_dir: Path) -> str:
    # The service gets the machine's environment, not a person's; spelled out (WinSW would expand a %NAME%) with the
    # release's own bin first: it also holds hirogate and the channel-plugin commands the server starts.
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    parts = [str(bin_dir), rf"{root}\System32", root, rf"{root}\System32\Wbem", rf"{root}\System32\WindowsPowerShell\v1.0"]
    return ";".join(parts)


def _package_name(pyproject: Path) -> str | None:
    try:
        return tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {}).get("name")
    except (OSError, tomllib.TOMLDecodeError):
        log.debug("A pyproject.toml can't be read for its name", path=str(pyproject), exc_info=True)
        return None


def _checkout_args(uv: str, source: Path, release: Path) -> list[str]:
    """For an install from a checkout, what Simone's deploy does too (deploy/deploy.sh):

    - rebuild every package of the checkout's workspace: uv keeps a build of a local package by its version and
      pyproject.toml alone, so a changed checkout whose version didn't change would install the old code;
    - pin the rest to the checkout's uv.lock, the versions its checks tested.
    """
    root = next((p for p in (source, *source.parents) if (p / "uv.lock").is_file()), None)
    if root is None:
        return ["--refresh"]
    # The admin's pages are built into the package by npm, not by uv: a checkout without them would give a service
    # whose admin never opens (seen Nov 25, 2026). Simone's deploy builds them first; so must whoever installs here.
    if not (root / ADMIN_ASSETS / "index.html").is_file():
        raise ServiceError(
            f"This checkout's admin pages aren't built, so the service's admin would not open. Build them first: "
            f"npm --prefix {root.parent / 'admin_frontend'} run package:python"
        )
    names = {
        name
        for pyproject in root.glob("**/pyproject.toml")
        if not {".venv", "node_modules"} & set(pyproject.relative_to(root).parts)
        and (name := _package_name(pyproject))
    }
    out: list[str] = []
    for name in sorted(names):
        out += ["--refresh-package", name]
    package = _package_name(source / "pyproject.toml")
    if package:
        constraints = release / "constraints.txt"
        release.mkdir(parents=True, exist_ok=True)
        export = subprocess.run(  # noqa: S603 — uv by its full path, fixed arguments
            [uv, "export", "--frozen", "--no-emit-workspace", "--no-dev", "--no-hashes", "--package", package,
             "-o", str(constraints)],
            cwd=root, capture_output=True, text=True, timeout=300, check=False,
        )
        if export.returncode != 0:
            raise ServiceError(f"Could not read {root / 'uv.lock'} to pin the install; nothing was changed.")
        out += ["--constraints", str(constraints)]
    return out


def python_home_of(release: Path) -> Path | None:
    """The Python a release's tool environment runs on (``home`` in its ``pyvenv.cfg``)."""
    for cfg in sorted(release.glob("tools/*/pyvenv.cfg")):
        try:
            for line in cfg.read_text(encoding="utf-8").splitlines():
                key, sep, value = line.partition("=")
                if sep and key.strip() == "home":
                    return Path(value.strip())
        except OSError:
            log.debug("A pyvenv.cfg can't be read", path=str(cfg), exc_info=True)
    return None


def _is_within(path: Path, folder: Path) -> bool:
    child, parent = PureWindowsPath(path), PureWindowsPath(folder)
    return child == parent or parent in child.parents


def install_release(lay: Layout, source: str) -> Path:
    """Install Hiro League (``source``: a package spec or a checkout's path) into a new release folder; return its
    ``hiro.exe``. A failed install leaves nothing behind."""
    uv = shutil.which("uv")
    if uv is None:
        raise ServiceError("uv is needed to install Hiro League for the service, and it is not on PATH.")
    release = lay.releases_dir / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    env = {
        **os.environ,
        "UV_TOOL_DIR": str(release / "tools"),
        "UV_TOOL_BIN_DIR": str(release / "bin"),
        "UV_PYTHON_INSTALL_DIR": str(lay.python_dir),
    }
    log.info("Installing Hiro League for the service", source=source, release=str(release))
    try:
        # --managed-python: uv's own Python, in the Hiro home. Without it uv takes a Python already on this PC, which
        # sits in a person's profile the service's account can't read (seen Nov 25, 2026: every start exited 103).
        args = [uv, "tool", "install", "--python", PYTHON_VERSION, "--managed-python"]
        if Path(source).is_dir():
            args += _checkout_args(uv, Path(source), release)
        # Its output goes to this terminal: a first install takes minutes, and the person watches it.
        result = subprocess.run(  # noqa: S603 — uv by its full path, fixed arguments
            [*args, source], env=env, timeout=_INSTALL_TIMEOUT_S, check=False,
        )
        exe = release / "bin" / "hiro.exe"
        if result.returncode != 0 or not exe.is_file():
            raise ServiceError(
                f"Installing Hiro League ({source}) for the service failed (uv exit code {result.returncode}); "
                "nothing was changed."
            )
        check = subprocess.run([str(exe), "--help"], capture_output=True, timeout=300, check=False)  # noqa: S603
        if check.returncode != 0:
            raise ServiceError(f"The new install's hiro.exe does not run ({exe}); nothing was changed.")
        # The check above runs as the person installing, who can read their own profile: prove the Python is one
        # the service's account can read too.
        python_home = python_home_of(release)
        if python_home is None or not _is_within(python_home, lay.home):
            raise ServiceError(
                f"The new install's Python is {python_home or 'unknown'}, outside {lay.home}: the service's account "
                "could not start it. Nothing was changed."
            )
    except (ServiceError, OSError, subprocess.TimeoutExpired) as exc:
        shutil.rmtree(release, ignore_errors=True)  # only the folder this install made
        if isinstance(exc, ServiceError):
            raise
        raise ServiceError(f"Installing Hiro League for the service failed: {exc}") from exc
    return exe


def build_spec(*, exe: Path, lay: Layout, workspace: str | None) -> WinswSpec:
    name = service_name(workspace)
    arguments = ["start", "--foreground"]
    if workspace:
        arguments += ["--workspace", workspace]
    return WinswSpec(
        id=name,
        name=f"HiroLeague ({name})",
        description=SERVICE_DESCRIPTION if not workspace else f"{SERVICE_DESCRIPTION} ({workspace})",
        executable=exe,
        arguments=arguments,
        working_directory=lay.data_dir,
        log_dir=lay.logs_dir,
        environment={
            # The service's account has an empty keyring nobody can fill: keys come from the secrets file.
            "PYTHON_KEYRING_BACKEND": NULL_KEYRING_BACKEND,
            ENV_SERVICE_MANAGER: "winsw",
            ENV_SECRETS_FILE: str(lay.secrets_file(name)),
            ENV_DATA_DIR: str(lay.data_dir),
            "PATH": _system_path(exe.parent),
            "PYTHONUNBUFFERED": "1",
            # WinSW writes what the server prints to a file: UTF-8, so a line with an emoji doesn't fail.
            "PYTHONIOENCODING": "utf-8",
        },
    )


def env_file_content(name: str) -> str:
    return render_env_file(
        service_name=name,
        user=f"NT SERVICE\\{name}",
        restart_command=f"Restart-Service {name}   (in an administrator PowerShell)",
        sections=provider_env_sections(),
        reader_line=f"# Secrets for the HiroLeague service '{name}': the server reads this file each time it starts.",
        access_line=f"# Only administrators and the service's own account (NT SERVICE\\{name}) can read it. Keep it that way.",
    )


def write_secrets_file(path: Path, content: str) -> bool:
    """Create the secrets file unless it exists; True when created. An existing one keeps its values."""
    if path.exists():
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        log.error("❌ Could not write the service's secrets file — HiroServer · service", path=str(path), error=str(exc))
        raise ServiceError(f"Could not write {path}: {exc}") from exc
    return True


def exe_from_config(binary_path: str) -> Path | None:
    """The service's WinSW path, as the service manager has it registered (``sc qc``), quotes and arguments off."""
    text = binary_path.strip()
    if text.startswith('"'):
        text = text[1:].split('"', 1)[0]
    else:
        text = text.split(" ", 1)[0]
    return Path(text) if text else None
