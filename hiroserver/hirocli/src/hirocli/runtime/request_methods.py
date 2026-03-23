"""Request method handlers — registered with RequestHandler at startup.

Each handler is an async function:
    async def handler(params: dict, ctx: RequestContext) -> dict

Handlers delegate to Tools so the same code path serves CLI, Agent,
HTTP, Admin UI, and WebSocket requests.
"""

from __future__ import annotations

from typing import Any

from ..tools.conversation import (
    ConversationChannelListTool,
    MessageHistoryTool,
)
from .request_handler import RequestContext, RequestHandler


async def handle_channels_list(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    tool = ConversationChannelListTool()
    result = tool.execute()
    return {"channels": result.channels}


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
    return {"messages": result.messages}


def register_request_methods(handler: RequestHandler) -> None:
    """Register all data-plane request methods."""
    handler.register("channels.list", handle_channels_list)
    handler.register("messages.history", handle_messages_history)
