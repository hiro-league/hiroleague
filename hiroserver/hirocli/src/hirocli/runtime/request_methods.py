"""Request method handlers — registered with RequestHandler at startup.

Each handler is an async function:
    async def handler(params: dict, ctx: RequestContext) -> dict[str, Any] | None

``None`` means the handler already emitted all outbound envelopes (e.g. ``files.get``).

Handlers delegate to Tools where practical so the same code path serves
CLI, Agent, HTTP, Admin UI, and WebSocket requests.
"""

from __future__ import annotations

from typing import Any, Final

from hiro_commons.log import Logger

from ..domain.blob_store import (
    DEFAULT_CHUNK_SIZE,
    blob_id_for_file,
    chunk_count_for_size,
)
from ..domain.character import resolve_character_photo_file_for_http
from ..domain.files_resolver import resolve_blob_id
from ..tools.character import CharacterListTool
from ..tools.conversation import (
    ConversationChannelListTool,
    MessageHistoryTool,
)
from ..tools.files import FilesHeadTool
from ..tools.policy import PolicyGetTool
from .envelope_factory import EnvelopeFactory
from .request_handler import RequestContext, RequestHandler
from .stream_sender import send_file_as_stream

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


async def handle_characters_list(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    del params
    tool = CharacterListTool()
    result = tool.execute(workspace=ctx.server_ctx.workspace_name)
    rows_out: list[dict[str, Any]] = []
    for row in result.characters:
        r = dict(row)
        cid = r.get("id")
        if isinstance(cid, str) and cid.strip():
            r["photo_ref"] = f"character_photo:{cid.strip()}"
            try:
                path, media_type = resolve_character_photo_file_for_http(ctx.workspace_path, cid.strip())
                r["photo_blob_id"] = blob_id_for_file(path)
                r["photo_media_type"] = media_type
            except FileNotFoundError:
                r["photo_blob_id"] = None
                r["photo_media_type"] = None
        rows_out.append(r)
    payload: dict[str, Any] = {"characters": rows_out}
    versions = ctx.resource_versions
    if versions is not None:
        payload["resource_sync_version"] = versions.get("characters")
    log.fineinfo(
        "Resource served — request:characters.list",
        count=len(rows_out),
        version=payload.get("resource_sync_version"),
    )
    return payload


async def handle_files_head(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    ref = params.get("ref")
    if not isinstance(ref, str) or not ref.strip():
        raise ValueError("ref is required")
    tool = FilesHeadTool()
    meta = tool.execute(ref=ref.strip(), workspace=ctx.server_ctx.workspace_name)
    log.info(
        "⬇️ Resource served — request:files.head",
        blob_id=meta.blob_id,
        size=meta.size,
        chunk_count=meta.chunk_count,
    )
    return {
        "blob_id": meta.blob_id,
        "size": meta.size,
        "media_type": meta.media_type,
        "chunk_size": meta.chunk_size,
        "chunk_count": meta.chunk_count,
    }


async def handle_files_get(params: dict[str, Any], ctx: RequestContext) -> None:
    blob_id_raw = params.get("blob_id")
    if not isinstance(blob_id_raw, str) or not blob_id_raw.strip():
        raise ValueError("blob_id is required")
    blob_id = blob_id_raw.strip()
    emit = ctx.emit_outbound
    if emit is None:
        raise RuntimeError("emit_outbound is required for files.get")

    path, _media_type = resolve_blob_id(ctx.workspace_path, blob_id)
    size = path.stat().st_size
    chunk_count = chunk_count_for_size(size, DEFAULT_CHUNK_SIZE)
    log.info(
        "⬇️ Resource served — request:files.get",
        blob_id=blob_id,
        size=size,
        chunk_count=chunk_count,
    )
    ack = EnvelopeFactory.response(
        ctx.msg,
        status="ok",
        payload={
            "session_id": ctx.msg.request_id,
            "chunk_count": chunk_count,
        },
    )
    await emit(ack)
    await send_file_as_stream(
        origin_request=ctx.msg,
        file_path=path,
        blob_id=blob_id,
        emit=emit,
        chunk_size=DEFAULT_CHUNK_SIZE,
    )
    terminal = EnvelopeFactory.response(
        ctx.msg,
        status="ok",
        payload={"blob_id": blob_id, "size": size},
    )
    await emit(terminal)


_REGISTERED_HANDLERS: Final[tuple[tuple[str, Any], ...]] = (
    ("channels.list", handle_channels_list),
    ("characters.list", handle_characters_list),
    ("files.head", handle_files_head),
    ("files.get", handle_files_get),
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
