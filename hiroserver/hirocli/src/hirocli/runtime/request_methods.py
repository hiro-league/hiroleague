"""Request method handlers — registered with RequestHandler at startup.

Each handler is an async function:
    async def handler(params: dict, ctx: RequestContext) -> dict

Handlers delegate to Tools so the same code path serves CLI, Agent,
HTTP, Admin UI, and WebSocket requests.
"""

from __future__ import annotations

from typing import Any, Final

from hiro_commons.log import Logger

from ..tools.conversation import (
    ConversationChannelListTool,
    MessageHistoryTool,
)
from ..tools.policy import PolicyGetTool
from .request_handler import RequestContext, RequestHandler

log = Logger.get("REQUEST")


async def handle_channels_list(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    del params
    tool = ConversationChannelListTool()
    result = tool.execute(workspace_path=ctx.workspace_path)
    payload: dict[str, Any] = {"channels": result.channels}
    versions = ctx.resource_versions
    if versions is not None:
        # Tier 2: monotonic counter shared with resource.changed (see ResourceVersionStore).
        payload["resource_sync_version"] = versions.get("channels")
    log.fineinfo(
        "Resource served — request:channels.list",
        count=len(result.channels),
        version=payload.get("resource_sync_version"),
    )
    return payload


async def handle_messages_history(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    channel_id = params.get("channel_id")
    if channel_id is None:
        raise ValueError("channel_id is required")
    tool = MessageHistoryTool()
    result = tool.execute(
        channel_id=int(channel_id),
        after=params.get("after"),
        limit=params.get("limit", 50),
    )
    log.fineinfo(
        "Resource served — request:messages.history",
        channel_id=channel_id,
        count=len(result.messages),
        after=params.get("after"),
    )
    return {"messages": result.messages}


async def handle_policy_get(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    del params
    tool = PolicyGetTool()
    result = tool.execute(workspace_path=ctx.workspace_path)
    payload = dict(result.snapshot)
    versions = ctx.resource_versions
    if versions is not None:
        # Tier 2: policy resource clock — distinct from snapshot.schema ``version``.
        payload["resource_sync_version"] = versions.get("policy")
    log.fineinfo(
        "Resource served — request:policy.get",
        version=payload.get("resource_sync_version"),
    )
    return payload


_REGISTERED_HANDLERS: Final[tuple[tuple[str, Any], ...]] = (
    ("channels.list", handle_channels_list),
    ("messages.history", handle_messages_history),
    ("policy.get", handle_policy_get),
)

REGISTERED_REQUEST_METHOD_NAMES: frozenset[str] = frozenset(
    name for name, _ in _REGISTERED_HANDLERS
)


def register_request_methods(handler: RequestHandler) -> None:
    """Register all data-plane request methods."""
    for name, fn in _REGISTERED_HANDLERS:
        handler.register(name, fn)
