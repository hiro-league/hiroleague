"""Install tools: an app installed, started, stopped and removed by the core (Installing apps, phase 5).

The steps are services/app_install.py's; the person's admin step between them is ``hiro extension system``, run by
the CLI (commands/extension.py), never by a tool. Every tool here is for the command line and the control server
only: Hiro's agent is never offered them (no ``agent`` surface), and none takes a path: a package reaches the core as
bytes (the control server's ``PUT /packages``) and is named by its id.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from hiro_commons.log import Logger

from ..domain import installs
from ..domain.hiro_home import app_folder
from ..domain.packages import PackageRefused
from ..domain.workspace import resolve_workspace
from ..runtime import stories
from ..services import app_install
from .base import Tool, ToolParam

log = Logger.get("EXTENSIONS.INSTALL")

_WORKSPACE = ToolParam(str, "Workspace name (default: registry default)", required=False)


def _resolve_path(workspace: str | None) -> Path:
    entry, _ = resolve_workspace(workspace)
    return Path(entry.path)


def _item_key(text: str) -> tuple[str, str]:
    permission, _, subject = text.strip().partition(":")
    return permission, subject


@dataclass
class InstallSheetResult:
    """What the person is asked before the admin step, or why the package can't be installed (``refused``)."""

    key: str = ""
    title: str = ""
    version: str = ""
    port: int = 0
    items: list[dict[str, Any]] = field(default_factory=list)  # permission, subject, words, required, why, understood
    refused: str = ""  # the code (bad_manifest, name_taken, core_version, port_taken), "" when it can be installed
    words: str = ""


@dataclass
class InstallStepResult:
    """Where one install stands after a step; ``job`` is the system part's (install: key, command)."""

    key: str
    state: str = ""
    step: str = ""
    job: dict[str, Any] = field(default_factory=dict)
    refused: str = ""
    words: str = ""


@dataclass
class InstallsResult:
    installs: list[dict[str, Any]] = field(default_factory=list)


def install_row(row: installs.Install) -> dict[str, Any]:
    """One install as the CLI and the admin read it, with its folders and whether its service runs."""
    from .. import app_system

    folder = app_folder(row.key, Path(row.home))
    return {
        "key": row.key, "title": row.title, "version": row.version, "port": row.port, "state": row.state,
        "step": row.step, "service": row.service, "running": app_system.is_running(row.service),
        "folder": str(folder.root), "data": str(folder.data), "installed_at": row.installed_at,
        "approved": [i.model_dump() for i in row.consent],
    }


class ExtensionInstallSheetTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "extension_install_sheet"
    description = "What an app in a package handed to the core asks, before the person approves its install"
    params = {"package": ToolParam(str, "The package's id (from PUT /packages)"), "workspace": _WORKSPACE}

    def execute(self, package: str, workspace: str | None = None) -> InstallSheetResult:
        workspace_path = _resolve_path(workspace)
        try:
            found = app_install.read_sheet(workspace_path, package)
        except PackageRefused as exc:
            return InstallSheetResult(refused=exc.code, words=str(exc))
        manifest = found.package.manifest
        items = [{"permission": a.permission, "subject": a.subject, "words": a.words, "required": a.required,
                  "why": a.why, "understood": a.understood} for a in found.items]
        return InstallSheetResult(key=manifest.key, title=manifest.title, version=manifest.version, port=found.port,
                                  items=items)


class ExtensionInstallPrepareTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "extension_install_prepare"
    description = ("The person approved an app's install: keep what they approved (every required item, the optional "
                   "ones named or all) and answer the job for the admin step")
    params = {
        "package": ToolParam(str, "The package's id (from PUT /packages)"),
        "optional": ToolParam(list, "Optional items approved too (permission or permission:subject)", required=False),
        "all": ToolParam(bool, "Every optional item approved too", required=False),
        "in_advance": ToolParam(bool, "The yes was given in advance (--approve), not when asked", required=False),
        "workspace": _WORKSPACE,
    }

    def execute(self, package: str, optional: list[str] | None = None, all: bool = False,  # noqa: A002
                in_advance: bool = False, workspace: str | None = None) -> InstallStepResult:
        workspace_path = _resolve_path(workspace)
        chosen = None if all else {_item_key(x) for x in (optional or [])}
        try:
            row, job = app_install.prepare(workspace_path, package, chosen, in_advance=in_advance)
        except PackageRefused as exc:
            return InstallStepResult(key="", refused=exc.code, words=str(exc))
        return InstallStepResult(key=row.key, state=row.state, job=job.model_dump())


class ExtensionInstallCancelTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "extension_install_cancel"
    description = ("An install stopped before it finished: forget it when nothing outside the core was made, else keep "
                   "it failed for removing")
    params = {"key": ToolParam(str, "The app's key"), "workspace": _WORKSPACE}

    def execute(self, key: str, workspace: str | None = None) -> InstallStepResult:
        gone = app_install.cancel(_resolve_path(workspace), key)
        return InstallStepResult(key=key, state="" if gone else "kept")


class ExtensionInstallFinishTool(Tool):
    """Runs in the core (``runtime``): on Windows only the core's account holds the right on the app's service."""

    surfaces = frozenset({"cli", "http"})
    runtime = True
    name = "extension_install_finish"
    description = "After the admin step: unpack an approved install, write its environment and start its service"
    params = {"key": ToolParam(str, "The app's key"), "workspace": _WORKSPACE}

    def execute(self, key: str, workspace: str | None = None) -> InstallStepResult:
        workspace_path = _resolve_path(workspace)
        row = installs.get_install(workspace_path, key)
        title = row.title if row else key
        with stories.started(stories.EXTENSION_INSTALL, "extensions.install", area="EXTENSIONS", own=True,
                             title=f"{title} installed"):
            try:
                done = app_install.finish(workspace_path, key)
            except app_install.InstallFailed as exc:
                found = installs.get_install(workspace_path, key)
                return InstallStepResult(key=key, state=found.state if found else "", step=str(exc),
                                         refused="failed", words=str(exc))
        return InstallStepResult(key=key, state=done.state, step=done.step)


class ExtensionInstallsTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "extension_installs"
    description = "The apps the core installed: their version, port, state, folders and whether their service runs"
    params = {"workspace": _WORKSPACE}

    def execute(self, workspace: str | None = None) -> InstallsResult:
        return InstallsResult(installs=[install_row(r) for r in installs.list_installs(_resolve_path(workspace))])


class _ServiceTool(Tool):
    """Start or stop an installed app's service with the core's own right (runs in the core)."""

    surfaces = frozenset({"cli", "http"})
    runtime = True
    params = {"key": ToolParam(str, "The app's key"), "workspace": _WORKSPACE}
    _start = True

    def execute(self, key: str, workspace: str | None = None) -> InstallStepResult:
        from .. import app_system

        row = installs.get_install(_resolve_path(workspace), key)
        if row is None:
            return InstallStepResult(key=key, refused="not_installed", words=f"“{key}” isn't installed by the core.")
        if row.state == installs.UPGRADING:
            return InstallStepResult(key=key, state=row.state, refused="upgrading",
                                     words=f"{row.title} is upgrading ({row.step}): it starts and stops by itself.")
        try:
            (app_system.start if self._start else app_system.stop)(row.service)
        except app_system.ServiceError as exc:
            return InstallStepResult(key=key, state=row.state, refused="failed", words=str(exc))
        log.info(f"{'▶️ App started' if self._start else '⏹️ App stopped'} — {row.title}", key=key)
        return InstallStepResult(key=key, state=row.state, step="started" if self._start else "stopped")


class ExtensionStartTool(_ServiceTool):
    name = "extension_start"
    description = "Start an installed app's service"


class ExtensionStopTool(_ServiceTool):
    name = "extension_stop"
    description = "Stop an installed app's service"
    _start = False


@dataclass
class UpgradeResult:
    """Where an upgrade ended: ``upgraded``, ``stayed`` (never switched, or went back), ``failed`` or ``refused``."""

    key: str
    title: str = ""
    before: str = ""
    to: str = ""
    outcome: str = ""
    words: str = ""
    new_asks: list[str] = field(default_factory=list)


class ExtensionUpgradeTool(Tool):
    """Runs in the core (``runtime``): it stops and starts the app's service with the core's right."""

    surfaces = frozenset({"cli", "http"})
    runtime = True
    name = "extension_upgrade"
    description = ("Upgrade an installed app from a package handed to the core: its migrations tried on a copy first, "
                   "then switched, health-checked, and put back by itself when the new version doesn't answer")
    params = {
        "key": ToolParam(str, "The installed app's key"),
        "package": ToolParam(str, "The package's id (from PUT /packages)"),
        "allow_row_loss": ToolParam(list, "Tables the new version's migrations may empty (the owner names them)",
                                    required=False),
        "workspace": _WORKSPACE,
    }

    def execute(self, key: str, package: str, allow_row_loss: list[str] | None = None,
                workspace: str | None = None) -> UpgradeResult:
        from ..services import app_upgrade

        workspace_path = _resolve_path(workspace)
        row = installs.get_install(workspace_path, key)
        with stories.started(stories.EXTENSION_UPGRADE, "extensions.upgrade", area="EXTENSIONS", own=True,
                             title=f"{row.title if row else key} upgrade"):
            try:
                done = app_upgrade.upgrade(workspace_path, key, package, allow_row_loss or [])
            except PackageRefused as exc:
                log.warning(f"⚠️ Upgrade refused — {key}: {exc}", key=key, code=exc.code)
                return UpgradeResult(key=key, outcome="refused", words=str(exc))
        return UpgradeResult(**asdict(done))


@dataclass
class InstallForgetResult:
    key: str
    forgotten: bool = False
    removed: dict[str, Any] = field(default_factory=dict)  # the paired record's removal (ExtensionRemoveResult)


class ExtensionInstallForgetTool(Tool):
    """Runs in the core (``runtime``): the running core keeps preferences in memory and announces the names."""

    surfaces = frozenset({"cli", "http"})
    runtime = True
    name = "extension_install_forget"
    description = ("After the admin step removed an installed app's service: drop its record, names, grants, picks, "
                   "releases and install")
    params = {"key": ToolParam(str, "The app's key"), "workspace": _WORKSPACE}

    def execute(self, key: str, workspace: str | None = None) -> InstallForgetResult:
        from .extension import ExtensionRemoveTool

        workspace_path = _resolve_path(workspace)
        row = installs.get_install(workspace_path, key)
        with stories.started(stories.EXTENSION_REMOVE, "extensions.remove", area="EXTENSIONS",
                             title=f"{row.title if row else key} removed"):
            removed: dict[str, Any] = {}
            extension_id = app_install.paired_id(workspace_path, key)
            if extension_id:
                removed = asdict(ExtensionRemoveTool().execute(extension_id=extension_id, workspace=workspace))
            gone = app_install.forget(workspace_path, key)
        return InstallForgetResult(key=key, forgotten=gone is not None, removed=removed)


# ---------------------------------------------------------------------------
# Channels: a uv tool the core starts itself (services/channel_install.py)
# ---------------------------------------------------------------------------


@dataclass
class ChannelLifecycleResult:
    """Where a channel's install, upgrade or removal ended; ``refused`` is the code when it didn't happen."""

    name: str
    package: str = ""
    before: str = ""
    version: str = ""
    refused: str = ""
    words: str = ""
    gone: list[str] = field(default_factory=list)


def _channel_manager(tool: Tool) -> Any:
    rt = getattr(tool, "_runtime", None)
    return rt.comm_manager.ctx.extension_manager if rt is not None else None


class ExtensionChannelInstallTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "extension_install_channel"
    description = ("Install a channel of the core's catalog (WhatsApp): its program as a uv tool of its published "
                   "package, then its row, switched off")
    params = {
        "channel_name": ToolParam(str, "The channel's name, e.g. 'whatsapp'"),
        "version": ToolParam(str, "A version of its package on PyPI (default: the newest, or this checkout's)",
                             required=False),
        "workspace": _WORKSPACE,
    }

    def execute(self, channel_name: str, version: str = "", workspace: str | None = None) -> ChannelLifecycleResult:
        from ..services import channel_install

        workspace_path = _resolve_path(workspace)
        with stories.started(stories.EXTENSION_INSTALL, "extensions.install", area="EXTENSIONS", own=True,
                             title=f"{channel_name} installed"):
            try:
                package, done = channel_install.install(workspace_path, workspace, channel_name, version)
            except channel_install.ChannelInstallRefused as exc:
                return ChannelLifecycleResult(name=channel_name, refused=exc.code, words=str(exc))
            except RuntimeError as exc:
                log.warning(f"⚠️ Channel install failed — {channel_name}: {exc}", channel=channel_name)
                return ChannelLifecycleResult(name=channel_name, refused="failed", words=str(exc))
        return ChannelLifecycleResult(name=channel_name, package=package, version=done)


class ExtensionChannelUpgradeTool(Tool):
    """Runs in the core when it runs (``runtime``): the plugin is stopped first (Windows holds a running program's
    files) and started again after, when it is switched on."""

    surfaces = frozenset({"cli", "http"})
    runtime = True
    name = "extension_upgrade_channel"
    description = "Upgrade a channel's program: installed again from where it came from, or a version from PyPI"
    params = {
        "channel_name": ToolParam(str, "The channel's name, e.g. 'whatsapp'"),
        "version": ToolParam(str, "A version of its package on PyPI (default: from where it was installed)",
                             required=False),
        "workspace": _WORKSPACE,
    }

    def attach_runtime(self, ctx: Any) -> None:
        self._runtime = ctx

    def execute(self, channel_name: str, version: str = "", workspace: str | None = None) -> ChannelLifecycleResult:
        from ..domain.channel_config import load_channel_config
        from ..services import channel_install

        if load_channel_config(_resolve_path(workspace), channel_name) is None:
            return ChannelLifecycleResult(name=channel_name, refused="not_installed",
                                          words=f"“{channel_name}” isn't installed: install it first.")
        with stories.started(stories.EXTENSION_UPGRADE, "extensions.upgrade", area="EXTENSIONS", own=True,
                             title=f"{channel_name} upgrade"):
            try:
                before, after = channel_install.upgrade(channel_name, version)
            except channel_install.ChannelInstallRefused as exc:
                return ChannelLifecycleResult(name=channel_name, refused=exc.code, words=str(exc))
            except RuntimeError as exc:
                log.warning(f"⚠️ Channel upgrade failed — {channel_name}: {exc}", channel=channel_name)
                return ChannelLifecycleResult(name=channel_name, refused="failed", words=str(exc))
        return ChannelLifecycleResult(name=channel_name, before=before, version=after)

    async def execute_async(self, channel_name: str, version: str = "",
                            workspace: str | None = None) -> ChannelLifecycleResult:
        import asyncio

        from ..domain.channel_config import load_channel_config

        manager = _channel_manager(self)
        cfg = await asyncio.to_thread(load_channel_config, _resolve_path(workspace), channel_name)
        if manager is not None and cfg is not None:
            await manager.deactivate(channel_name)
        try:
            return await asyncio.to_thread(self.execute, channel_name, version, workspace)
        finally:
            # Started again whatever happened: a failed upgrade leaves the program uv had, which may still run
            if manager is not None and cfg is not None and cfg.enabled:
                await manager.activate(channel_name)


class ExtensionChannelRemoveTool(Tool):
    """Runs in the core when it runs (``runtime``): the plugin is stopped before its program is uninstalled."""

    surfaces = frozenset({"cli", "http"})
    runtime = True
    name = "extension_remove_channel"
    description = ("Remove a channel: stopped, its row and settings dropped, its program uninstalled; with purge its "
                   "folder (its key and its account's link) and its secrets too")
    params = {
        "channel_name": ToolParam(str, "The channel's name, e.g. 'whatsapp'"),
        "purge": ToolParam(bool, "Delete its folder and secrets too", required=False),
        "workspace": _WORKSPACE,
    }

    def attach_runtime(self, ctx: Any) -> None:
        self._runtime = ctx

    def execute(self, channel_name: str, purge: bool = False, workspace: str | None = None) -> ChannelLifecycleResult:
        from ..domain.extensions import KIND_CHANNEL, list_paired_extensions
        from ..services import channel_install
        from .extension import ExtensionRemoveTool

        workspace_path = _resolve_path(workspace)
        try:
            channel_install.catalog_entry(channel_name)  # the phones' channel goes with the core
        except channel_install.ChannelInstallRefused as exc:
            if exc.code == "mandatory":
                return ChannelLifecycleResult(name=channel_name, refused=exc.code, words=str(exc))
            # Not in the catalog (a channel set up by hand, hiro channel setup): it is removed all the same
        found = next((e for e in list_paired_extensions(workspace_path, kind=KIND_CHANNEL)
                      if e.name == channel_name and e.started_by_core), None)
        if found is None:
            return ChannelLifecycleResult(name=channel_name, refused="not_installed",
                                          words=f"“{channel_name}” isn't installed.")
        secrets = channel_install.secret_keys_of(workspace_path, channel_name) if purge else []
        with stories.started(stories.EXTENSION_REMOVE, "extensions.remove", area="EXTENSIONS",
                             title=f"{channel_name} removed"):
            removed = ExtensionRemoveTool().execute(extension_id=found.extension_id, workspace=workspace)
            gone = ["its row and settings"] + (["its program"] if removed.uninstalled else [])
            if purge:
                try:
                    gone += channel_install.purge(workspace_path, channel_name, secrets)
                except (RuntimeError, OSError) as exc:
                    log.warning(f"⚠️ Channel removed, but not purged — {channel_name}: {exc}", channel=channel_name)
                    return ChannelLifecycleResult(name=channel_name, refused="failed", gone=gone,
                                                  words=f"Removed, but its folder stayed: {exc}")
        words = "" if removed.uninstalled else "Its program stayed installed (the log says why)."
        return ChannelLifecycleResult(name=channel_name, gone=gone, words=words)

    async def execute_async(self, channel_name: str, purge: bool = False,
                            workspace: str | None = None) -> ChannelLifecycleResult:
        import asyncio

        from .channel import mandatory_channel

        manager = _channel_manager(self)
        if manager is not None and not mandatory_channel(channel_name):
            await manager.deactivate(channel_name)  # a no-op when it doesn't run
        result = await asyncio.to_thread(self.execute, channel_name, purge, workspace)
        rt = getattr(self, "_runtime", None)
        if rt is not None and not result.refused:
            getattr(rt.comm_manager.ctx, "channel_status", {}).pop(channel_name, None)
        return result
