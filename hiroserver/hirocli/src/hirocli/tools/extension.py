"""Extension tools — pairing codes, the paired list, removal, and the listen address.

Extensions are programs that run on their own (HomeHiro first) and sign in on the
workspace's extension socket (runtime/extension_manager.py). The CLI
(commands/extension.py) and the admin (admin/features/extensions) call these.
Live state (who is connected, the test call) comes from the running server's
ExtensionManager, read by the admin route directly.
"""

from __future__ import annotations

import asyncio
import json
import shlex
import socket
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from hiro_commons.constants.domain import MANDATORY_CHANNEL_NAME
from hiro_commons.constants.network import DEFAULT_LOCALHOST
from hiro_commons.log import Logger

from ..domain.config import Config, load_config, save_config
from ..domain.channel_catalog import catalog_channel
from ..domain.channel_config import list_channel_configs
from ..domain.channel_descriptor import load_channel_descriptor
from ..domain.features import feature_active
from ..domain.events import DomainEvent, DomainEventType, get_domain_event_bus
from ..domain.extensions import (
    KIND_APP,
    KIND_CHANNEL,
    RESERVED_NAMES,
    PairedExtension,
    get_paired_extension,
    list_paired_extensions,
    remove_paired_extension,
    start_extension_pairing,
)
from ..domain.people import drop_source_rights
from ..domain import approvals, person_tokens
from ..domain.site_names import list_claims, release
from ..runtime import stories
from ..domain.workspace import resolve_workspace
from .base import Tool, ToolParam
from .channel import ChannelRemoveTool, ChannelUninstallTool, mandatory_channel

# Addresses that mean "every interface": an extension can't dial these, so the
# address shown to type in uses this machine's name instead.
_ANY_ADDRESSES = frozenset({"0.0.0.0", "::", ""})


log = Logger.get("EXTENSIONS")


def _resolve_path(workspace: str | None) -> Path:
    entry, _ = resolve_workspace(workspace)
    return Path(entry.path)


def extension_address(config: Config) -> str:
    """The ws:// address an extension types in to reach this workspace."""
    host = config.extension_host.strip()
    if host in _ANY_ADDRESSES:
        host = socket.gethostname()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"  # IPv6 literal
    return f"ws://{host}:{config.effective_extension_port()}"


def _iso(value: Any) -> str | None:
    return value.isoformat().replace("+00:00", "Z") if value else None


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class ExtensionAddResult:
    code: str
    expires_at: str
    address: str
    # A code that pairs one paired app again: its name ("" = a code for a new app)
    pairs_again: str = ""


@dataclass
class ExtensionListResult:
    extensions: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ExtensionRemoveResult:
    removed: bool
    extension_id: str
    kind: str = ""
    name: str = ""
    # A channel's program is uninstalled with it; False when that part failed (its row is gone all the same).
    uninstalled: bool = False
    # An app takes with it what the core kept under its name; its own data stays where the app keeps it.
    site_name: str = ""  # the LAN name it gave back
    rights_dropped: dict[str, list[str]] = field(default_factory=dict)  # role id → the keys it held
    picks_dropped: list[str] = field(default_factory=list)  # "<section>: <key>", as preferences.json had them


@dataclass
class ExtensionAddressResult:
    host: str
    port: int
    address: str
    changed: bool
    restart_required: bool
    note: str = ""


@dataclass
class ExtensionNamesResult:
    """This machine's setup for apps' LAN names (docs/site-names-design.md)."""

    ip: str
    caddy_file: str
    caddy_main: str
    caddy_reload: list[str]
    names: list[dict[str, Any]]
    changed: bool
    restart_required: bool


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class ExtensionAddTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "extension_add"
    description = "Generate a short-lived pairing code to connect an extension (such as HomeHiro) to this workspace"
    params = {
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
        "ttl_seconds": ToolParam(int, "Pairing code lifetime in seconds", required=False),
    }

    def execute(self, workspace: str | None = None, ttl_seconds: int | None = None) -> ExtensionAddResult:
        workspace_path = _resolve_path(workspace)
        config = load_config(workspace_path)
        session = start_extension_pairing(
            workspace_path,
            code_length=config.pairing_code_length,
            ttl_seconds=ttl_seconds or config.pairing_code_ttl_seconds,
        )
        return ExtensionAddResult(
            code=session.code,
            expires_at=session.expires_at.isoformat().replace("+00:00", "Z"),
            address=extension_address(config),
        )


class ExtensionPairAgainTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "extension_pair_again"
    description = (
        "Generate a pairing code for one paired app that lost its key: it pairs again keeping its rights, AI picks "
        "and LAN name"
    )
    params = {
        "extension_id": ToolParam(str, "The app's extension ID (see `hiro extension list`)"),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, extension_id: str, workspace: str | None = None) -> ExtensionAddResult:
        workspace_path = _resolve_path(workspace)
        ext = get_paired_extension(workspace_path, extension_id)
        if ext is None:
            raise ValueError("That extension isn't in the list any more.")
        if ext.kind != KIND_APP:
            raise ValueError(f"{ext.name} is a channel: the core pairs it by itself when it starts it.")
        config = load_config(workspace_path)
        session = start_extension_pairing(
            workspace_path,
            code_length=config.pairing_code_length,
            ttl_seconds=config.pairing_code_ttl_seconds,
            extension_id=ext.extension_id,
        )
        log.info(f"Pairing code to pair {ext.name} again", extension_id=ext.extension_id)
        return ExtensionAddResult(
            code=session.code,
            expires_at=session.expires_at.isoformat().replace("+00:00", "Z"),
            address=extension_address(config),
            pairs_again=ext.name,
        )


def _site(info: dict[str, Any]) -> dict[str, Any] | None:
    """The app's site entry (kind "site") from what it offers, or None."""
    shows = (info.get("offers") or {}).get("shows") or []
    return next((e for e in shows if isinstance(e, dict) and e.get("kind") == "site"), None)


def _label(ext: PairedExtension) -> str:
    """The name people read: an app's site title, a channel's catalog label, else its name."""
    if ext.kind == KIND_CHANNEL:
        entry = catalog_channel(ext.name)
        return entry.label if entry is not None else ext.name.capitalize()
    site = _site(ext.info) or {}
    return str(site.get("title") or ext.name)


def _offers(info: dict[str, Any]) -> list[dict[str, str]]:
    """What other extensions or Hiro may ask it: its knows and can_do entries, by name and what each says."""
    offers = info.get("offers") or {}
    out: list[dict[str, str]] = []
    for entry in [*(offers.get("knows") or []), *(offers.get("can_do") or [])]:
        if isinstance(entry, dict) and entry.get("name"):
            out.append({"name": str(entry["name"]), "says": str(entry.get("says") or "")})
    return out


def _uses(info: dict[str, Any]) -> list[str]:
    """The AI and voice uses it declared, by name."""
    return [
        str(use.get("name") or use.get("id"))
        for key in ("uses", "voice_uses")
        for use in info.get(key) or []
        if isinstance(use, dict) and (use.get("name") or use.get("id"))
    ]


def _hidden(ext: PairedExtension) -> bool:
    """The phones' channel is left out of the list while the `devices` feature is hidden (features.py)."""
    return ext.kind == KIND_CHANNEL and ext.name == MANDATORY_CHANNEL_NAME and not feature_active(MANDATORY_CHANNEL_NAME)


def extension_row(ext: PairedExtension, workspace_path: Path, enabled: dict[str, bool]) -> dict[str, Any]:
    """One row of the one list, for an app or a channel; what is live (connected, linked) the caller adds."""
    channel = ext.kind == KIND_CHANNEL
    descriptor = load_channel_descriptor(workspace_path, ext.name) if channel else None
    schema = (descriptor.config_schema if descriptor is not None else None) or {}
    capabilities = (descriptor.capabilities if descriptor is not None else None) or {}
    catalog = catalog_channel(ext.name) if channel else None
    site = None if channel else _site(ext.info)
    return {
        "extension_id": ext.extension_id,
        "name": ext.name,
        "label": _label(ext),
        "kind": ext.kind,
        "version": str(ext.info.get("version") or ""),
        "description": str(ext.info.get("description") or (catalog.description if catalog else "")),
        "paired_at": _iso(ext.paired_at),
        "last_seen": _iso(ext.last_seen),
        "relays_chat": ext.relays_chat,
        "started_by_core": ext.started_by_core,
        # A started extension's switch; an app has none.
        "enabled": enabled.get(ext.name) if channel else None,
        "mandatory": channel and mandatory_channel(ext.name),
        # Its settings form, when the core keeps its settings, and how its account is linked ("qr"), if it has one.
        "has_settings": bool(schema.get("properties")),
        "pairing": str(capabilities.get("pairing") or "") if channel else "",
        "site": str(site.get("url") or "") if site else "",
        "offers": _offers(ext.info),
        "uses": _uses(ext.info),
    }


class ExtensionListTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "extension_list"
    description = "List every extension of this workspace: its channel plugins and its apps"
    params = {
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, workspace: str | None = None) -> ExtensionListResult:
        workspace_path = _resolve_path(workspace)
        enabled = {cfg.name: cfg.enabled for cfg in list_channel_configs(workspace_path)}
        return ExtensionListResult(
            extensions=[
                extension_row(ext, workspace_path, enabled)
                for ext in list_paired_extensions(workspace_path, kind=None)
                if not _hidden(ext)
            ]
        )


@dataclass
class ExtensionApprovalResult:
    """An app's approval as the owner sees it (Permissions phase 8)."""

    extension_id: str
    name: str
    approved_for_everything: bool
    pending: bool
    waits: bool
    items: list[dict[str, Any]] = field(default_factory=list)
    claimed: list[str] = field(default_factory=list)  # LAN names the approval let the core claim for it


def _approval_result(found: Any, claimed: list[str] | None = None) -> ExtensionApprovalResult:
    return ExtensionApprovalResult(
        extension_id=found.extension_id, name=found.name, approved_for_everything=found.approved_for_everything,
        pending=found.pending, waits=found.waits, items=[asdict(i) for i in found.items], claimed=claimed or [],
    )


def _find_app(workspace_path: Path, extension: str) -> PairedExtension:
    """An app by its id or its name; raises ValueError when none."""
    for e in list_paired_extensions(workspace_path):
        if extension in (e.extension_id, e.name):
            return e
    raise ValueError(f"No paired app is called {extension!r}.")


class ExtensionApprovalTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "extension_approval"
    description = "What a paired app asks to do on its own, what the owner approved and what waits for a yes"
    params = {
        "extension": ToolParam(str, "The app's name or id"),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, extension: str, workspace: str | None = None) -> ExtensionApprovalResult:
        workspace_path = _resolve_path(workspace)
        app = _find_app(workspace_path, extension)
        found = approvals.view(workspace_path, app.extension_id)
        if found is None:
            raise ValueError(f"No paired app is called {extension!r}.")
        return _approval_result(found)


class ExtensionApproveTool(Tool):
    """The owner's yes to what an app asks (Permissions phase 8): every required item, and the optional ones named
    (or all of them). In the running server the LAN name it was approved for is claimed and the app is told."""

    surfaces = frozenset({"cli", "http"})
    runtime = True
    name = "extension_approve"
    description = (
        "Approve what a paired app asks to do on its own: every required item, and the optional ones named "
        "(`permission` or `permission:subject`), or every one with all"
    )
    params = {
        "extension": ToolParam(str, "The app's name or id"),
        "optional": ToolParam(list, "Optional items to approve (permission or permission:subject)", required=False),
        "all": ToolParam(bool, "Approve every optional item too", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def attach_runtime(self, ctx: Any) -> None:
        self._runtime = ctx

    def execute(self, extension: str, optional: list[str] | None = None, all: bool = False,  # noqa: A002
                workspace: str | None = None) -> ExtensionApprovalResult:
        workspace_path = _resolve_path(workspace)
        app = _find_app(workspace_path, extension)
        chosen = None if all else {_item_key(x) for x in (optional or [])}
        with stories.started(stories.EXTENSION_APPROVED, "extensions.approve", area="EXTENSIONS",
                             title=f"{app.name} approved"):
            approved, claims = approvals.approve_app(workspace_path, app.extension_id, chosen)
            log.info(f"✅ App approved — {app.name}: {len(approved)} item(s)", extension_id=app.extension_id,
                     items=", ".join(f"{i.permission}{':' + i.subject if i.subject else ''}" for i in approved))
        found = approvals.view(workspace_path, app.extension_id)
        assert found is not None  # approve_app raised for an app gone meanwhile
        return _approval_result(found, claims)

    async def execute_async(self, extension: str, optional: list[str] | None = None, all: bool = False,  # noqa: A002
                            workspace: str | None = None) -> ExtensionApprovalResult:
        result = await asyncio.to_thread(self.execute, extension, optional, all, workspace)
        rt = getattr(self, "_runtime", None)
        if rt is not None:
            from ..runtime.approval_effects import after_approval

            await after_approval(rt.comm_manager.ctx, result.extension_id, result.claimed)
        return result


def _item_key(text: str) -> tuple[str, str]:
    permission, _, subject = text.strip().partition(":")
    return (permission, subject)


class ExtensionRemoveTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "extension_remove"
    description = (
        "Remove an extension: an app loses its key and is refused until paired again; "
        "a channel plugin loses its settings and its program is uninstalled"
    )
    params = {
        "extension_id": ToolParam(str, "Extension ID to remove"),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, extension_id: str, workspace: str | None = None) -> ExtensionRemoveResult:
        workspace_path = _resolve_path(workspace)
        ext = next((e for e in list_paired_extensions(workspace_path, kind=None) if e.extension_id == extension_id), None)
        if ext is None:
            return ExtensionRemoveResult(removed=False, extension_id=extension_id)
        if ext.kind != KIND_CHANNEL:
            return _remove_app(workspace_path, ext)
        # A channel: the core installed its program, so removing it uninstalls it too (raises for the mandatory one).
        removed = ChannelRemoveTool().execute(ext.name, workspace).removed
        uninstalled = False
        try:
            ChannelUninstallTool().execute(ext.name)
            uninstalled = True
        except (RuntimeError, OSError) as exc:
            # Its row is gone already; a program left installed must not fail the removal.
            log.warning("⚠️ Extensions: removed a channel, but its program stayed installed", channel=ext.name, error=str(exc))
        return ExtensionRemoveResult(
            removed=removed, extension_id=extension_id, kind=ext.kind, name=ext.name, uninstalled=uninstalled
        )


# Where an app's picks live in preferences.json: maps keyed "<app>:<use>" (AI, voice, embedding, reranker uses), and
# the folders its AI asks may name, keyed by the app's name alone.
_PICKS_BY_USE = ("ai.uses", "voice.uses", "embedding.uses", "rerank.uses")
_PICKS_BY_NAME = ("ai.folders",)


def picks_without(prefs: Any, name: str) -> tuple[dict[str, Any], list[str]]:
    """The preference edits that drop an app's picks, and what they drop ("<section>: <key>"). Matches the name
    exactly, so removing ``home`` leaves ``homehiro``'s alone."""
    edits: dict[str, Any] = {}
    dropped: list[str] = []
    for path in (*_PICKS_BY_USE, *_PICKS_BY_NAME):
        section, field_name = path.split(".")
        current: dict[str, Any] = dict(getattr(getattr(prefs, section), field_name))
        if path in _PICKS_BY_USE:
            gone = [k for k in current if k.partition(":")[0] == name]
        else:
            gone = [k for k in current if k == name]
        if gone:
            edits[path] = {k: v for k, v in current.items() if k not in gone}
            dropped += [f"{path}: {k}" for k in gone]
    return edits, dropped


def _remove_app(workspace_path: Path, ext: PairedExtension) -> ExtensionRemoveResult:
    """Forget an app and what the core kept under its name: its key, its LAN name, every role's grants in it and its
    AI and voice picks. Its own data is the app's and stays. In the running server (the admin, or the CLI through
    /invoke) the name stops being announced and Caddy's file is written again at once; otherwise at the next start."""
    from ..runtime.preferences_runtime import preferences_runtime_for

    if not remove_paired_extension(workspace_path, ext.extension_id):
        return ExtensionRemoveResult(removed=False, extension_id=ext.extension_id, kind=ext.kind, name=ext.name)
    person_tokens.end_for_app(workspace_path, ext.extension_id)  # Permissions phase 8: the proofs it held end
    site_name = release(workspace_path, ext.extension_id) or ""
    rights: dict[str, list[str]] = {}
    picks: list[str] = []
    # Grants and picks are kept under the name: only when no other extension holds it (two apps could share one
    # before names were unique), and never the core's own.
    shared = ext.name in RESERVED_NAMES or any(e.name == ext.name for e in list_paired_extensions(workspace_path, kind=None))
    if ext.name and not shared:
        rights = drop_source_rights(workspace_path, ext.name)
        runtime = preferences_runtime_for(workspace_path)
        edits, picks = picks_without(runtime.current, ext.name)
        if edits:
            runtime.update_many(edits)
    get_domain_event_bus().publish(DomainEvent(
        type=DomainEventType.EXTENSION_REMOVED,
        workspace_path=workspace_path,
        payload={"extension_id": ext.extension_id, "name": ext.name, "site_name": site_name},
    ))
    # What went, in full, so a removal by mistake can be set again by hand.
    log.info(
        f"🗑️ App removed — {ext.name or ext.extension_id}: its name {site_name or '(none)'}, rights in "
        f"{len(rights)} role(s), {len(picks)} pick(s); its own data stays",
        extension_id=ext.extension_id,
        site_name=site_name,
        rights=json.dumps(rights),
        picks=", ".join(picks),
        kept_by_name="another extension holds the same name" if shared else "",
    )
    return ExtensionRemoveResult(
        removed=True, extension_id=ext.extension_id, kind=ext.kind, name=ext.name,
        site_name=site_name, rights_dropped=rights, picks_dropped=picks,
    )


class ExtensionAddressTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "extension_address"
    description = (
        "Show or set the address extensions connect on (127.0.0.1 = this machine only; "
        "the Docker bridge or LAN address reaches extensions elsewhere). Needs a restart."
    )
    params = {
        "host": ToolParam(str, "Address to listen on; omit to only show it", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, host: str | None = None, workspace: str | None = None) -> ExtensionAddressResult:
        workspace_path = _resolve_path(workspace)
        config = load_config(workspace_path)
        changed = False
        if host is not None:
            new_host = host.strip() or DEFAULT_LOCALHOST
            if new_host != config.extension_host:
                config.extension_host = new_host
                save_config(workspace_path, config)
                changed = True
        local = config.extension_host in {DEFAULT_LOCALHOST, "localhost", "::1"}
        return ExtensionAddressResult(
            host=config.extension_host,
            port=config.effective_extension_port(),
            address=extension_address(config),
            changed=changed,
            restart_required=changed,
            note=(
                ""
                if local
                else "Not encrypted: fine on the Docker bridge; on a LAN, anyone on the network "
                "can read the messages (sign-in still holds)."
            ),
        )


class ExtensionNamesTool(Tool):
    """Apps' LAN names: show or set this machine's setup, and list the names apps have claimed."""

    surfaces = frozenset({"cli", "http"})
    name = "extension_names"
    description = (
        "Show or set how apps' LAN names are set up on this machine: the LAN address names point at (empty = off), "
        "the Caddy file the core writes, the hand-written Caddyfile (its names are taken), and the command that "
        "reloads Caddy. Lists the names apps claimed. Needs a restart."
    )
    params = {
        "ip": ToolParam(str, "LAN address the names point at; empty string = names off; omit to keep", required=False),
        "caddy_file": ToolParam(str, "File the core writes for Caddy; omit to keep", required=False),
        "caddy_main": ToolParam(str, "The hand-written Caddyfile; omit to keep", required=False),
        "caddy_reload": ToolParam(str, "Command that reloads Caddy, e.g. 'docker restart caddy'; omit to keep", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(
        self,
        ip: str | None = None,
        caddy_file: str | None = None,
        caddy_main: str | None = None,
        caddy_reload: str | None = None,
        workspace: str | None = None,
    ) -> ExtensionNamesResult:
        workspace_path = _resolve_path(workspace)
        config = load_config(workspace_path)
        before = config.model_dump()
        if ip is not None:
            config.site_names_ip = ip.strip()
        if caddy_file is not None:
            config.site_names_caddy_file = caddy_file.strip()
        if caddy_main is not None:
            config.site_names_caddy_main = caddy_main.strip()
        if caddy_reload is not None:
            config.site_names_caddy_reload = shlex.split(caddy_reload)
        changed = config.model_dump() != before
        if changed:
            save_config(workspace_path, config)
        names = [
            {"name": c.name, "extension_id": c.extension_id, "port": c.port, "claimed_at": c.claimed_at}
            for c in list_claims(workspace_path)
        ]
        return ExtensionNamesResult(
            ip=config.site_names_ip,
            caddy_file=config.site_names_caddy_file,
            caddy_main=config.site_names_caddy_main,
            caddy_reload=list(config.site_names_caddy_reload),
            names=names,
            changed=changed,
            restart_required=changed,
        )
