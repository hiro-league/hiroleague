"""The elevated system part's job, and its check (the design's §8, "Who may do what"). Pure.

The core never holds admin rights: installing or removing an app needs one step a person approves (sudo, or Windows'
prompt), `hiro extension system <job file>`, the only code that runs elevated for apps. It takes one job from the
core: install or remove, a key, the program the service runs. Everything else it works out itself, never from the job:
the account and the service (``hiro-<key, dashed>``), the folder (``<its own Hiro home>/apps/<key>``), and the account
the core runs as (the one its own service runs as). So a job can't make it touch another account, service or folder.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from hiro_channel_sdk.manifest import key_problem

from .extension_keys import key_refusal
from .hiro_home import AppFolder, app_folder
from .packages import service_name

INSTALL = "install"
REMOVE = "remove"
_COMMAND = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")


class SystemJob(BaseModel):
    """One job for the system part. ``command`` is the console script the service runs (install only)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: Literal["install", "remove"]
    key: str
    command: str = ""
    purge: bool = False  # remove: the app's data goes too


class JobRefused(ValueError):
    """The system part won't do this job; the message is for people."""


@dataclass(frozen=True)
class AppSystem:
    """What one job means on this machine, worked out by the system part itself."""

    key: str
    service: str  # hiro-<key, dashed>: the service's name and its account's
    account: str
    folder: AppFolder
    command: str


def check_job(job: SystemJob, home: Path) -> AppSystem:
    """The job as the system part will do it, or JobRefused: the key must pass the key rule, the command must be a
    plain program name (an install's), and everything else follows from the key and this machine's Hiro home."""
    problem = key_problem(job.key) or key_refusal(job.key)
    if problem:
        raise JobRefused(problem)
    if job.action == INSTALL and not _COMMAND.fullmatch(job.command):
        raise JobRefused(f"{job.command!r} isn't a program name such as example-hello.")
    if job.action == INSTALL and job.purge:
        raise JobRefused("An install job can't purge.")
    name = service_name(job.key)
    return AppSystem(key=job.key, service=name, account=name, folder=app_folder(job.key, home), command=job.command)
