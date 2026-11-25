"""Extension routes: the one list of every extension (channel plugins and apps) with live
status, pairing codes, removal, the listen address, and the core's test call.

Live state comes from the running server's ExtensionManager (``ctx.extension_manager``)
and a channel's link from its status (``ctx.channel_status``); both apply only when the
selected workspace is the one this server runs. A channel's switch, settings and link
are the channel routes' (channels.py): only an extension the core starts has them.
"""

from __future__ import annotations

import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from hiro_channel_sdk.constants import METHOD_EXTENSION_INFO
from hiro_channel_sdk.extension import ExtensionRequestError

from hirocli.admin.features.extensions.service import ExtensionService
from hirocli.domain import approvals
from hirocli.domain.extensions import KIND_CHANNEL
from hirocli.runtime.approval_effects import after_approval
from hirocli.tools.extension import ExtensionApprovalTool, ExtensionApproveTool
from hirocli.tools.channel import mandatory_channel
from hirocli.admin_svelte.deps import SelectedWorkspaceIdDep
from hirocli.admin_svelte.result_payload import _api_data, api_failure

extensions_router = APIRouter()


class AddressBody(BaseModel):
    host: str


class ExtensionOffer(BaseModel):
    name: str
    says: str


class ExtensionRow(BaseModel):
    """One extension of the one list: what its row and About panel show."""

    extension_id: str
    name: str
    label: str
    kind: str
    version: str
    description: str
    paired_at: str | None
    last_seen: str | None
    relays_chat: bool
    started_by_core: bool
    enabled: bool | None
    mandatory: bool
    has_settings: bool
    pairing: str
    site: str
    offers: list[ExtensionOffer]
    uses: list[str]
    connected: bool
    connected_at: str | None
    remote: str | None
    # A channel with an account (pairing): whether it is linked now, and to which account.
    linked: bool | None
    account: str
    # Permissions phase 8: an app never answered (it gets nothing it asks for), and an app with something that waits
    pending: bool = False
    waits: bool = False
    waiting_count: int = 0


class ExtensionListen(BaseModel):
    host: str = ""
    port: int = 0
    address: str = ""
    changed: bool = False
    restart_required: bool = False
    note: str = ""
    listening: bool | None = None
    error: str | None = None
    live_host: str | None = None


class ExtensionList(BaseModel):
    listen: ExtensionListen
    extensions: list[ExtensionRow]


class ExtensionRemoved(BaseModel):
    message: str


# The states in which a channel's account is linked (the plugin's channel.status).
_LINKED_STATES = frozenset({"connected", "paired", "ready"})


def _live_manager(request: Request, workspace_path: Path | None) -> Any:
    """The running ExtensionManager when it serves the selected workspace, else None."""
    ctx = getattr(request.app.state, "ctx", None)
    manager = getattr(ctx, "extension_manager", None) if ctx is not None else None
    if manager is None or workspace_path is None:
        return None
    try:
        same = Path(ctx.workspace_path).resolve() == workspace_path.resolve()
    except OSError:
        same = False
    return manager if same else None


@extensions_router.get("/extensions", response_model=ExtensionList)
async def list_extensions(request: Request, workspace_id: SelectedWorkspaceIdDep) -> Any:
    service = ExtensionService()
    listed = await run_in_threadpool(service.list_extensions, workspace_id)
    if not listed.ok:
        return _api_data(listed)
    address = await run_in_threadpool(service.address, workspace_id)
    workspace_path = await run_in_threadpool(service.workspace_path, workspace_id)
    manager = _live_manager(request, workspace_path)
    live = manager.snapshot(kind=None) if manager is not None else {}
    statuses = getattr(request.app.state.ctx, "channel_status", {}) if manager is not None else {}
    extensions = []
    views = await run_in_threadpool(_approval_views, workspace_path, [e["extension_id"] for e in listed.data or []
                                                                      if e["kind"] != KIND_CHANNEL])
    for ext in listed.data or []:
        conn = live.get(ext["extension_id"])
        approval = views.get(ext["extension_id"])
        status = statuses.get(ext["name"], {}) if ext["kind"] == KIND_CHANNEL else {}
        extensions.append(
            {
                **ext,
                "connected": conn is not None,
                "connected_at": conn["connected_at"] if conn else None,
                "remote": conn["remote"] if conn else None,
                # The live connection knows the current version; the table the last one.
                "version": (conn["info"].get("version") if conn else None) or ext["version"],
                "linked": (status.get("state") in _LINKED_STATES) if ext["pairing"] and manager is not None else None,
                "account": str(status.get("account") or ""),
                "pending": bool(approval and approval.pending),
                "waits": bool(approval and approval.waits),
                "waiting_count": sum(1 for i in approval.items if i.waiting) if approval else 0,
            }
        )
    listen = asdict(address.data) if address.ok and address.data is not None else {}
    if manager is not None:
        state = manager.listen_state()
        # What the server is actually doing, which can differ from config until a restart.
        listen.update({"listening": state["listening"], "error": state["error"], "live_host": state["host"]})
    else:
        listen.update({"listening": None, "error": None, "live_host": None})
    return {"listen": listen, "extensions": extensions}


def _approval_views(workspace_path: Path | None, extension_ids: list[str]) -> dict[str, approvals.AppApproval]:
    if workspace_path is None:
        return {}
    out = {}
    for eid in extension_ids:
        found = approvals.view(workspace_path, eid)
        if found is not None:
            out[eid] = found
    return out


# ---------------------------------------------------------------------------
# Permissions phase 8: what an app is approved for (the owner's alone: route_rules.py)
# ---------------------------------------------------------------------------


class ApprovalItem(BaseModel):
    permission: str
    subject: str
    words: str
    required: bool
    why: str
    approved: bool
    waiting: bool
    understood: bool


class AppApproval(BaseModel):
    extension_id: str
    name: str
    approved_for_everything: bool
    pending: bool
    waits: bool
    items: list[ApprovalItem]
    claimed: list[str] = []


class ApproveBody(BaseModel):
    """The optional items switched on, as "permission" or "permission:subject"; every required one goes with them."""

    optional: list[str] = []


@extensions_router.get("/extensions/{extension_id}/approval", response_model=AppApproval)
async def get_extension_approval(extension_id: str, workspace_id: SelectedWorkspaceIdDep) -> Any:
    """What the app asks to do on its own, what is approved and what waits."""
    try:
        result = await run_in_threadpool(ExtensionApprovalTool().execute, extension_id, workspace_id)
    except ValueError as exc:
        return api_failure(str(exc), 404)
    return asdict(result)


@extensions_router.put("/extensions/{extension_id}/approval", response_model=AppApproval)
async def approve_extension(
    extension_id: str, body: ApproveBody, request: Request, workspace_id: SelectedWorkspaceIdDep
) -> Any:
    """The owner's yes: every required item, and the optional ones switched on. The app's LAN name is claimed and
    the app is told, when the running server serves this workspace."""
    try:
        result = await run_in_threadpool(
            ExtensionApproveTool().execute, extension_id, body.optional, False, workspace_id
        )
    except (ValueError, LookupError) as exc:
        return api_failure(str(exc), 404)
    workspace_path = await run_in_threadpool(ExtensionService().workspace_path, workspace_id)
    if _live_manager(request, workspace_path) is not None:
        await after_approval(request.app.state.ctx, result.extension_id, result.claimed)
    return asdict(result)


@extensions_router.post("/extensions/pairing-code")
async def generate_extension_pairing_code(workspace_id: SelectedWorkspaceIdDep) -> Any:
    result = await run_in_threadpool(ExtensionService().generate_pairing_code, workspace_id)
    if not result.ok or result.data is None:
        return _api_data(result)
    return asdict(result.data)


@extensions_router.post("/extensions/{extension_id}/pair-again")
async def pair_extension_again(extension_id: str, workspace_id: SelectedWorkspaceIdDep) -> Any:
    """A pairing code for one paired app that lost its key: it pairs again on its own record, keeping its rights, AI
    picks and LAN name."""
    result = await run_in_threadpool(ExtensionService().pair_again_code, extension_id, workspace_id)
    if not result.ok or result.data is None:
        return _api_data(result)
    return asdict(result.data)


@extensions_router.delete("/extensions/{extension_id}", response_model=ExtensionRemoved)
async def remove_extension(
    extension_id: str, request: Request, workspace_id: SelectedWorkspaceIdDep
) -> Any:
    """Remove one extension: an app is forgotten (it pairs again with a new code); a channel is stopped, its
    settings deleted and its program uninstalled. The mandatory channel is refused."""
    service = ExtensionService()
    ext = await run_in_threadpool(service.find, extension_id, workspace_id)
    if ext is None:
        return api_failure("That extension isn't in the list any more.", 404)
    channel = ext.kind == KIND_CHANNEL
    if channel and mandatory_channel(ext.name):
        return api_failure(f"{ext.name} can't be removed: phones' chat needs it.")
    workspace_path = await run_in_threadpool(service.workspace_path, workspace_id)
    manager = _live_manager(request, workspace_path)
    if channel and manager is not None:
        await manager.deactivate(ext.name)  # stop its process first; a no-op when it isn't running
    result = await run_in_threadpool(service.remove_extension, extension_id, workspace_id)
    if not result.ok or result.data is None:
        return _api_data(result)
    if manager is not None:
        if channel:
            getattr(request.app.state.ctx, "channel_status", {}).pop(ext.name, None)
        else:
            # Close it now; it is refused when it tries again.
            await manager.disconnect(extension_id)
    if not channel:
        gone = [f"its name {result.data.site_name}"] if result.data.site_name else []
        if result.data.rights_dropped:
            gone.append(f"its rights in {len(result.data.rights_dropped)} role(s)")
        if result.data.picks_dropped:
            gone.append(f"{len(result.data.picks_dropped)} AI or voice pick(s)")
        with_it = f", with {', '.join(gone)}" if gone else ""
        return {"message": f"{ext.name} removed{with_it}: it pairs again with a new code. Its own data stays."}
    if result.data.uninstalled:
        return {"message": f"{ext.name} removed, and its program uninstalled."}
    return {"message": f"{ext.name} removed; its program stayed installed (the server's log says why)."}


@extensions_router.put("/extensions/address")
async def set_extension_address(body: AddressBody, workspace_id: SelectedWorkspaceIdDep) -> Any:
    result = await run_in_threadpool(ExtensionService().address, workspace_id, body.host)
    if not result.ok or result.data is None:
        return _api_data(result)
    return asdict(result.data)


@extensions_router.post("/extensions/{extension_id}/info")
async def ask_extension_info(
    extension_id: str, request: Request, workspace_id: SelectedWorkspaceIdDep
) -> Any:
    """The core's test call: ask a connected extension for its name and version."""
    workspace_path = await run_in_threadpool(ExtensionService().workspace_path, workspace_id)
    manager = _live_manager(request, workspace_path)
    if manager is None:
        return api_failure("The server for this workspace isn't running here.")
    started = time.perf_counter()
    try:
        data = await manager.request(extension_id, METHOD_EXTENSION_INFO)
    except ExtensionRequestError as exc:
        return api_failure(exc.message)
    return {"info": data, "elapsed_ms": round((time.perf_counter() - started) * 1000)}
