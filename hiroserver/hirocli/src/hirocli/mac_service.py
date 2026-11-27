"""The Hiro server as a Mac LaunchDaemon: what `sudo hiro service install` puts on the system.

As on Linux, the server runs as a regular account (the one that installs it, or ``--user``) and keeps its workspace in
that account's own data folder, so that account's `hiro` sees the same workspace. The service's own files go in the
Hiro home, ``/Library/Application Support/HiroLeague``, owned by that account:

    <home>/<name>.env        the secrets file (provider keys), mode 0600, read by the server itself
    <home>/logs/<name>.log   what the server prints before its own log file is open (a failed start)
    <home>/channels/         the channels' programs the server installs (domain/hiro_home.py)

Builds the Hiro-specific parts and hands them to the generic ``hiro_commons.launchd_service``; mirrors
``hirocli.linux_service``.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

from hiro_commons.launchd_service import LaunchdSpec
from hiro_commons.systemd_service import NULL_KEYRING_BACKEND, ServiceError, ServiceUser, render_env_file

from .constants import ENV_SECRETS_FILE, ENV_SERVICE_MANAGER
from .domain.hiro_home import ENV_HIRO_HOME, channels_folder
from .linux_service import provider_env_sections, service_name

HOME = Path("/Library/Application Support/HiroLeague")
LABEL_PREFIX = "com.hiroleague"
_SYSTEM_PATH = "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
_RUN_CHECK_TIMEOUT_S = 180


def label(workspace: str | None) -> str:
    """``com.hiroleague.hiro`` for the default workspace, ``com.hiroleague.hiro-<workspace>`` for a named one."""
    return f"{LABEL_PREFIX}.{service_name(workspace)}"


def secrets_file(workspace: str | None) -> Path:
    return HOME / f"{service_name(workspace)}.env"


def log_file(workspace: str | None) -> Path:
    return HOME / "logs" / f"{service_name(workspace)}.log"


def sudo_command(exe: str, action: str, *, user: str | None, workspace: str | None,
                 core_name: str | None = None) -> str:
    parts = ["sudo", exe, "service", action]
    if user:
        parts += ["--user", user]
    if workspace:
        parts += ["--workspace", workspace]
    if core_name:
        parts += ["--name", core_name]
    return " ".join(shlex.quote(p) for p in parts)


def build_spec(*, exe: str, user: ServiceUser, workspace: str | None) -> LaunchdSpec:
    args = [exe, "start", "--foreground"]
    if workspace:
        args += ["--workspace", workspace]
    return LaunchdSpec(
        label=label(workspace),
        user=user.name,
        program_args=args,
        working_directory=user.home,
        log_path=log_file(workspace),
        environment={
            # A daemon starts with no one signed in: the account's keychain is locked. Keys come from the file.
            "PYTHON_KEYRING_BACKEND": NULL_KEYRING_BACKEND,
            ENV_SERVICE_MANAGER: "launchd",
            ENV_SECRETS_FILE: secrets_file(workspace).as_posix(),
            ENV_HIRO_HOME: HOME.as_posix(),
            # Then the channels' commands the server starts: the home's path has a space, so a channel there is set up
            # by its bare command name, found on this PATH (tools/channel.installed_channel_command).
            "PATH": f"{Path(exe).parent.as_posix()}:{channels_folder(HOME).bin.as_posix()}:{_SYSTEM_PATH}",
            "HOME": user.home.as_posix(),
            "PYTHONUNBUFFERED": "1",
        },
    )


def env_file_content(name: str, user: str, workspace: str | None) -> str:
    return render_env_file(
        service_name=name,
        user=user,
        restart_command=f"sudo launchctl kickstart -k system/{label(workspace)}",
        sections=provider_env_sections(),
        reader_line=f"# Secrets for the HiroLeague service '{name}': the server reads this file each time it starts.",
    )


def prepare_home(user: ServiceUser, workspace: str | None) -> None:
    """Make the Hiro home, its logs folder and its channels' folder, owned by the service's account (it writes its log
    there and installs its channels there)."""
    try:
        for folder in (HOME, log_file(workspace).parent, channels_folder(HOME).root):
            folder.mkdir(mode=0o755, parents=True, exist_ok=True)
            os.chown(folder, user.uid, user.gid)
    except OSError as exc:
        raise ServiceError(f"Could not prepare {HOME}: {exc}") from exc


def check_user_can_run(user: ServiceUser, exe: str) -> None:
    """Run `hiro --help` as the service's account, so a program it can't read fails here, not at boot."""
    try:
        result = subprocess.run(  # noqa: S603 — sudo by its full path, fixed arguments
            ["/usr/bin/sudo", "-u", user.name, "--", exe, "--help"],
            capture_output=True, text=True, timeout=_RUN_CHECK_TIMEOUT_S, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ServiceError(f"Could not run {exe} as {user.name}: {exc}") from exc
    if result.returncode != 0:
        tail = "\n".join((result.stderr or result.stdout).strip().splitlines()[-5:])
        raise ServiceError(
            f"User '{user.name}' cannot run {exe}:\n{tail}\n"
            "Install Hiro League where that user can read it, or run the service as the user who installed it."
        )
