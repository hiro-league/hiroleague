"""The Extensions page's installed apps (Installing apps, phase 5): what each connected app still needs set, the
packages waiting in the Hiro home's ``packages`` folder, and an installed app's start, stop and upgrade.

Installing and removing need an administrator (one prompt), so the page gives their commands instead of buttons.
Starting, stopping and upgrading need none: the core does them with the right its install gave it. They are the
owner's (route_rules.py), as approving an app is: an upgrade runs the app's own code.
"""

from __future__ import annotations

import asyncio
import shlex
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from hiro_channel_sdk.constants import METHOD_EXTENSION_SETUP
from hiro_channel_sdk.extension import ExtensionRequestError
from hiro_channel_sdk.offers import SetupItem
from hiro_commons import tasks
from hiro_commons.log import Logger

from hirocli.admin.features.extensions.service import ExtensionService
from hirocli.admin_svelte.deps import SelectedWorkspaceIdDep
from hirocli.admin_svelte.result_payload import api_failure
from hirocli.domain import installs
from hirocli.domain.hiro_home import hiro_home
from hirocli.domain.packages import BAD_MANIFEST, PackageRefused, keep_package, open_package, version_numbers
from hirocli.services.app_upgrade import STEPS_IN_ORDER
from hirocli.tools.extension_install import ExtensionStartTool, ExtensionStopTool, ExtensionUpgradeTool

log = Logger.get("ADMIN.INSTALLS")

installs_router = APIRouter()

PACKAGES = "packages"
_SETUP_TIMEOUT_S = 5.0


class SetupLeft(BaseModel):
    """One thing an app still needs set, and where: a page of the app's own site (``app`` its name)."""

    title: str
    app: str | None
    path: str


class SetupAnswer(BaseModel):
    """By extension id: what each connected app still needs set (its done items left out); an app that didn't answer
    has its words in ``errors``."""

    left: dict[str, list[SetupLeft]]
    errors: dict[str, str]


class PackageOffer(BaseModel):
    """A package in the Hiro home's packages folder, and what it offers: ``install`` (not installed), ``upgrade``
    (newer than the installed one), or ``none`` (installed already, or older)."""

    file: str
    key: str
    title: str
    version: str
    offer: str
    command: str  # installing it takes one administrator step: the page gives the command


class Packages(BaseModel):
    folder: str
    packages: list[PackageOffer]
    refused: dict[str, str]  # a file that isn't a package, and why


class Commands(BaseModel):
    """What removing an installed app takes: one administrator step, so the page gives the commands."""

    remove: str
    purge: str


class UpgradeBody(BaseModel):
    file: str  # a package in the Hiro home's packages folder


class UpgradeState(BaseModel):
    """An upgrade the page started: running, then where it ended (the tool's outcome and words); ``steps`` are the
    core's own, in order, so the page follows the install's ``step``."""

    key: str
    running: bool
    title: str = ""
    before: str = ""
    to: str = ""
    outcome: str = ""
    words: str = ""
    new_asks: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=lambda: list(STEPS_IN_ORDER))


class ServiceAnswer(BaseModel):
    key: str
    step: str


# The upgrades this page started, by key: the job's state, read back while it runs
_UPGRADES: dict[str, dict[str, Any]] = {}


def packages_folder() -> Path:
    return hiro_home() / PACKAGES


def _command(*args: str) -> str:
    if sys.platform == "win32":
        return " ".join(f'"{a}"' if " " in a else a for a in args)
    return shlex.join(args)


def read_packages(folder: Path, installed: dict[str, str]) -> Packages:
    """The packages in ``folder`` and what each offers, against the installed versions (by key)."""
    offers: list[PackageOffer] = []
    refused: dict[str, str] = {}
    for path in sorted(folder.glob("*.zip")) if folder.is_dir() else []:
        try:
            manifest = open_package(path).manifest
        except PackageRefused as exc:
            refused[path.name] = str(exc)
            continue
        have = installed.get(manifest.key)
        if have is None:
            offer = "install"
        elif version_numbers(manifest.version) > version_numbers(have):
            offer = "upgrade"
        else:
            offer = "none"
        offers.append(PackageOffer(file=path.name, key=manifest.key, title=manifest.title, version=manifest.version,
                                   offer=offer, command=_command("hiro", "extension", "install", str(path))))
    return Packages(folder=str(folder), packages=offers, refused=refused)


def _installed(workspace_id: str | None) -> dict[str, str]:
    workspace_path = ExtensionService().workspace_path(workspace_id)
    return {r.key: r.version for r in installs.list_installs(workspace_path)} if workspace_path else {}


@installs_router.get("/extensions/packages", response_model=Packages)
async def list_packages(workspace_id: SelectedWorkspaceIdDep) -> Any:
    installed = await run_in_threadpool(_installed, workspace_id)
    return await run_in_threadpool(read_packages, packages_folder(), installed)


@installs_router.get("/extensions/setup", response_model=SetupAnswer)
async def list_setup(request: Request, workspace_id: SelectedWorkspaceIdDep) -> Any:
    """Ask every connected app what it still needs set (``extension.setup``), all at once; asked as the page opens,
    never kept. An app from before answers ``method_not_found``: nothing left."""
    from hirocli.admin_svelte.routes.extensions import _live_manager

    workspace_path = await run_in_threadpool(ExtensionService().workspace_path, workspace_id)
    manager = _live_manager(request, workspace_path)
    if manager is None:
        return {"left": {}, "errors": {}}
    apps = [eid for eid, conn in manager.snapshot().items() if conn]

    async def ask(extension_id: str) -> tuple[str, list[SetupLeft] | str]:
        try:
            answer = await manager.request(extension_id, METHOD_EXTENSION_SETUP, {}, timeout=_SETUP_TIMEOUT_S)
        except ExtensionRequestError as exc:
            return extension_id, ([] if exc.code == "method_not_found" else exc.message)
        except TimeoutError:
            return extension_id, "It didn't answer in time."
        left = []
        for raw in (answer or {}).get("items") or []:
            item = SetupItem.model_validate(raw)
            if not item.done:
                left.append(SetupLeft(title=item.title, app=item.link.app, path=item.link.path))
        return extension_id, left

    answers = await asyncio.gather(*(ask(eid) for eid in apps))
    return {"left": {eid: a for eid, a in answers if isinstance(a, list)},
            "errors": {eid: a for eid, a in answers if isinstance(a, str)}}


@installs_router.get("/extensions/installs/{key}/commands", response_model=Commands)
async def remove_commands(key: str) -> Any:
    return {"remove": _command("hiro", "extension", "remove", key),
            "purge": _command("hiro", "extension", "remove", key, "--purge")}


async def _service(tool: Any, key: str, workspace_id: str | None) -> Any:
    result = await run_in_threadpool(tool.execute, key=key, workspace=workspace_id)
    if result.refused:
        return api_failure(result.words, 404 if result.refused == "not_installed" else 409)
    return {"key": key, "step": result.step}


@installs_router.post("/extensions/installs/{key}/start", response_model=ServiceAnswer)
async def start_install(key: str, workspace_id: SelectedWorkspaceIdDep) -> Any:
    return await _service(ExtensionStartTool(), key, workspace_id)


@installs_router.post("/extensions/installs/{key}/stop", response_model=ServiceAnswer)
async def stop_install(key: str, workspace_id: SelectedWorkspaceIdDep) -> Any:
    return await _service(ExtensionStopTool(), key, workspace_id)


def hand_over(folder: Path, file: str, workspace_path: Path) -> str:
    """The package from the Hiro home's folder into the core's own store (an upgrade reads only that)."""
    path = (folder / file).resolve()
    if path.parent != folder.resolve() or not path.is_file():
        raise PackageRefused(BAD_MANIFEST, f"There's no package {file} in {folder}.")
    return keep_package(workspace_path, [path.read_bytes()])


@installs_router.post("/extensions/installs/{key}/upgrade", response_model=UpgradeState, status_code=202)
async def start_upgrade(key: str, body: UpgradeBody, workspace_id: SelectedWorkspaceIdDep) -> Any:
    """Start upgrading an installed app from a package in the Hiro home's packages folder: a job of the core, which
    the page follows (GET the same address, and the list's install step)."""
    if _UPGRADES.get(key, {}).get("running"):
        return api_failure("It is upgrading already.", 409)
    workspace_path = await run_in_threadpool(ExtensionService().workspace_path, workspace_id)
    if workspace_path is None:
        return api_failure("That workspace isn't known.", 404)
    try:
        package_id = await run_in_threadpool(hand_over, packages_folder(), body.file, workspace_path)
    except PackageRefused as exc:
        return api_failure(str(exc), 404)
    state: dict[str, Any] = {"key": key, "running": True}
    _UPGRADES[key] = state

    async def job() -> None:
        try:
            done = await asyncio.to_thread(ExtensionUpgradeTool().execute, key=key, package=package_id,
                                           workspace=workspace_id)
            state.update(asdict(done))
        finally:
            state["running"] = False

    tasks.keep(job(), name=f"upgrade {key}")
    log.info(f"Upgrade started from the admin — {key}", key=key, file=body.file)
    return state


@installs_router.get("/extensions/installs/{key}/upgrade", response_model=UpgradeState)
async def upgrade_state(key: str) -> Any:
    state = _UPGRADES.get(key)
    if state is None:
        return api_failure("No upgrade was started for it here.", 404)
    return state
