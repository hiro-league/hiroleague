"""The Hiro server as a Linux systemd service: what `hiro service install` puts on the system.

Builds the Hiro-specific parts (service name, the `hiro start --foreground` command line, the
environment, the secrets-file template from the provider catalog) and hands them to the generic
``hiro_commons.systemd_service``. Mirrors ``hirocli.autostart``, which does the same for Windows'
sign-in auto-start.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import sys
from pathlib import Path

from hiro_commons.systemd_service import (
    NULL_KEYRING_BACKEND,
    ServiceError,
    ServiceSpec,
    env_file_path,
    render_env_file,
    unit_file_name,
)

from .constants import ENV_SERVICE_MANAGER, SERVICE_RESTART_EXIT_CODE

SERVICE_BASE_NAME = "hiro"
SERVICE_DESCRIPTION = "HiroLeague server"
DOCS_URL = "https://docs.hiroleague.com/hiro/get-started/linux-service"
# Standard system PATH after the folder `hiro` lives in: that folder also holds hirogate and the
# channel-plugin commands the server starts (uv puts every tool's commands side by side).
_SYSTEM_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


def service_name(workspace: str | None) -> str:
    """``hiro`` for the default workspace, ``hiro-<workspace>`` for a named one."""
    if not workspace:
        return SERVICE_BASE_NAME
    slug = re.sub(r"[^A-Za-z0-9_.\-]+", "-", workspace).strip("-")
    if not slug:
        raise ServiceError(f"Cannot make a service name from workspace '{workspace}'.")
    return f"{SERVICE_BASE_NAME}-{slug}"


def hiro_executable() -> str:
    """Absolute path of the `hiro` being run, symlinks kept.

    Kept unresolved on purpose: a stable link such as /opt/hiroleague/current/bin/hiro is what
    the unit must call, so a new install (the link moving) is picked up on the next start.
    Under ``sudo`` the PATH is reset, so the running program's own path is preferred.
    """
    argv0 = sys.argv[0] if sys.argv else ""
    if argv0 and Path(argv0).name == "hiro" and os.path.isfile(argv0):
        return os.path.abspath(argv0)
    found = shutil.which("hiro")
    if found:
        return os.path.abspath(found)
    raise ServiceError(
        "Could not find the `hiro` program. Run this command through the installed `hiro`, "
        "e.g. `sudo /opt/hiroleague/current/bin/hiro service install`."
    )


def sudo_command(exe: str, action: str, *, user: str | None, workspace: str | None) -> str:
    """The exact command to re-run ``hiro service <action>`` as root.

    The full path to `hiro` because sudo resets PATH (``~/.local/bin`` is not on it), and
    ``--user`` spelled out so the service doesn't end up running as root.
    """
    parts = ["sudo", exe, "service", action]
    if user:
        parts += ["--user", user]
    if workspace:
        parts += ["--workspace", workspace]
    return " ".join(shlex.quote(p) for p in parts)


def build_spec(*, exe: str, user: str, group: str, workspace: str | None) -> ServiceSpec:
    name = service_name(workspace)
    exec_args = [exe, "start", "--foreground"]
    if workspace:
        exec_args += ["--workspace", workspace]
    bin_dir = str(Path(exe).parent).replace("\\", "/")
    return ServiceSpec(
        name=name,
        description=SERVICE_DESCRIPTION if not workspace else f"{SERVICE_DESCRIPTION} ({workspace})",
        user=user,
        group=group,
        exec_args=exec_args,
        env_file=env_file_path(name),
        environment={
            # No desktop keyring on a server: secrets come from the env file
            # (credential_store falls back to the catalog's env variables).
            "PYTHON_KEYRING_BACKEND": NULL_KEYRING_BACKEND,
            ENV_SERVICE_MANAGER: "systemd",
            "PATH": f"{bin_dir}:{_SYSTEM_PATH}",
            # Log lines reach the journal as they happen, not when a buffer fills.
            "PYTHONUNBUFFERED": "1",
        },
        restart_exit_code=SERVICE_RESTART_EXIT_CODE,
        documentation=DOCS_URL,
    )


def provider_env_sections() -> list[tuple[str, list[str]]]:
    """Every provider variable the server reads, from the bundled catalog (stays in sync with it)."""
    from .domain.model_catalog import get_model_catalog

    keys: list[str] = []
    accounts: list[str] = []
    for provider in get_model_catalog().list_providers():
        keys += [k for k in provider.credential_env_keys if k not in keys]
        accounts += [k for k in provider.account_env_keys if k not in accounts]
    return [
        ("Provider API keys: uncomment the ones you use and paste the key after '='.", keys),
        ("Provider account ids (only for the providers that need one).", accounts),
    ]


def env_file_content(name: str, user: str) -> str:
    return render_env_file(
        service_name=name,
        user=user,
        restart_command=f"sudo systemctl restart {unit_file_name(name)}",
        sections=provider_env_sections(),
    )
