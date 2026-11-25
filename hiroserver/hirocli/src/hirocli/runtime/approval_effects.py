"""What follows the owner's yes to an app, in the running server (Permissions phase 8): the LAN name it was
approved for is claimed, and the app is told what it has now (``approval.changed``), so its pages show it."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from hiro_channel_sdk.approvals import EVENT_APPROVAL_CHANGED
from hiro_commons.log import Logger

from ..domain import approvals
from ..domain.extensions import get_paired_extension
from ..domain.site_names import SiteNameError

if TYPE_CHECKING:
    from .server_context import ServerContext

log = Logger.get("APPROVALS")


async def after_approval(ctx: ServerContext, extension_id: str, claimed: list[str]) -> None:
    """Claim each LAN name newly approved ("name:port"), then tell the app what it is approved for and what waits."""
    names: Any = getattr(ctx, "site_names", None)
    for claim in claimed:
        name, _, port = claim.rpartition(":")
        if names is None or not port.isdigit():
            continue
        try:
            await names.claim(extension_id, name, int(port))
        except SiteNameError as exc:  # approved, but the name can't be set up: said; the app keeps asking for it
            log.warning(f"⚠️ App approved, but its LAN name wasn't claimed — {name}", error=str(exc))
    manager = ctx.extension_manager
    if manager is None:
        return
    record = await asyncio.to_thread(get_paired_extension, ctx.workspace_path, extension_id)
    if record is None:
        return
    wire = await asyncio.to_thread(approvals.on_the_wire, ctx.workspace_path, extension_id, record.info)
    await manager.send_event(extension_id, EVENT_APPROVAL_CHANGED, wire)
