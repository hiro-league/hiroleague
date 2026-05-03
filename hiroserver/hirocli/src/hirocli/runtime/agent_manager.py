"""AgentManager — LLM agent worker for Hiro.

Responsibilities:
  - Reads inbound messages from CommunicationManager.inbound_queue.
  - Builds agent input from text ContentItems and from metadata["description"]
    on non-text items (audio transcripts, image descriptions set by adapters).
  - Skips messages that yield no input text after checking both sources.
  - Passes each message to a LangChain v1 agent (create_agent, or when
    ``preferences.memory.summarization_enabled`` is true, a custom LangGraph
    graph with LangMem SummarizationNode — see summarizing_agent_graph).
  - Maintains per-conversation persistent memory keyed by conversation_channels.id
    (a UUID) using LangGraph's AsyncSqliteSaver checkpointer backed by workspace.db.
  - Constructs a reply UnifiedMessage and places it on the outbound queue.
  - On LLM errors, enqueues a human-readable fallback reply instead.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import time
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

from hiro_channel_sdk.constants import EVENT_TYPE_MESSAGE_VOICED, MESSAGE_TYPE_EVENT
from hiro_channel_sdk.models import ContentItem, EventPayload, MessageRouting, UnifiedMessage
from hiro_commons.log import Logger

# Reuse comm-log helpers so AGENT lines share peer, kind, and content_hint ordering with COMM_MAN.
from .comm_log import LOG_IN, LOG_OUT, comm_extras, comm_kind, comm_peer_label

if TYPE_CHECKING:
    from ..services.tts.service import TTSService
    from .communication_manager import CommunicationManager
    from .server_context import ServerContext

log = Logger.get("AGENT")

_FALLBACK_ERROR_BODY = (
    "Sorry, I encountered an error processing your message. Please try again."
)


def _reply_content_type(content: Any) -> str:
    if isinstance(content, list):
        return f"list[{len(content)}]"
    return type(content).__name__


def _normalize_reply_content(content: Any) -> str:
    """Convert LangChain/provider message content into Hiro's plain text body."""
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    if not isinstance(content, list):
        return str(content)

    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
            continue
        if not isinstance(block, dict):
            parts.append(str(block))
            continue

        text = block.get("text")
        if isinstance(text, str):
            parts.append(text)
            continue

        content_value = block.get("content")
        if isinstance(content_value, str):
            parts.append(content_value)

    return "\n".join(p for p in parts if p)


def _make_reply(inbound: UnifiedMessage, body: str) -> UnifiedMessage:
    if not isinstance(body, str):
        raise TypeError(f"reply body must be str, got {type(body).__name__}")
    # Preserve routing metadata (e.g. device_name injected by ChannelManager) for logs and downstream.
    return UnifiedMessage(
        routing=MessageRouting(
            channel=inbound.routing.channel,
            direction="outbound",
            sender_id="server",
            recipient_id=inbound.routing.sender_id,
            metadata=dict(inbound.routing.metadata or {}),
        ),
        content=[ContentItem(content_type="text", body=body)],
    )


class AgentManager:
    """Consumes inbound text messages and produces agent replies.

    Usage::

        agent_mgr = AgentManager(ctx, comm_manager, tts_service=tts)
        await asyncio.gather(..., agent_mgr.run())
    """

    def __init__(
        self,
        ctx: ServerContext,
        comm_manager: CommunicationManager,
        tts_service: TTSService | None = None,
    ) -> None:
        self._ctx = ctx
        self._comm = comm_manager
        self._tts_service = tts_service
        self._checkpointer = None
        self._credential_store = None
        self._agent_cache: OrderedDict[tuple[Any, ...], Any] = OrderedDict()
        self._agent_cache_max = 24

    def _build_agent(
        self,
        checkpointer,
        credential_store,
        *,
        llm_entry,
        system_prompt: str,
        prefs,
    ):
        """Compile LangGraph/LangChain agent for a resolved chat model and persona prompt."""
        from ..domain.model_factory import create_chat_model

        try:
            from langchain.agents import create_agent

            from ..domain.preferences import resolve_summarization_llm
            from ..tools import all_tools
            from ..tools.langchain_adapter import to_langchain_list
            from .summarizing_agent_graph import build_summarizing_agent_graph

            tools = to_langchain_list(all_tools())

            log.fineinfo(
                f"Building agent — chat · {llm_entry.model_id}",
                temperature=llm_entry.temperature,
                max_tokens=llm_entry.max_tokens,
                tools=len(tools),
            )

            model = create_chat_model(
                llm_entry.model_id,
                workspace_path=self._ctx.workspace_path,
                temperature=llm_entry.temperature,
                max_tokens=llm_entry.max_tokens,
                credential_store=credential_store,
            )

            if prefs.memory.summarization_enabled:
                sum_entry = resolve_summarization_llm(
                    prefs,
                    self._ctx.workspace_path,
                    credential_store=credential_store,
                )
                if sum_entry is None:
                    log.warning(
                        "⚠️ Summarization on but no LLM resolved — HiroServer · falling back to agent without summarization",
                    )
                    return create_agent(
                        model=model,
                        tools=tools,
                        system_prompt=system_prompt,
                        checkpointer=checkpointer,
                    )
                summarization_model = create_chat_model(
                    sum_entry.model_id,
                    workspace_path=self._ctx.workspace_path,
                    temperature=sum_entry.temperature,
                    max_tokens=sum_entry.max_tokens,
                    credential_store=credential_store,
                )
                log.info(
                    "✅ Agent summarization — preferences · LangMem SummarizationNode",
                    max_context_tokens=prefs.memory.max_context_tokens,
                    max_tokens_before_summary=(
                        prefs.memory.max_tokens_before_summary
                        or prefs.memory.max_context_tokens
                    ),
                    max_summary_tokens=prefs.memory.max_summary_tokens,
                    summarizer=sum_entry.model_id,
                )
                return build_summarizing_agent_graph(
                    model=model,
                    summarization_model=summarization_model,
                    tools=tools,
                    system_prompt=system_prompt,
                    checkpointer=checkpointer,
                    memory=prefs.memory,
                )

            return create_agent(
                model=model,
                tools=tools,
                system_prompt=system_prompt,
                checkpointer=checkpointer,
            )
        except Exception as exc:
            log.error(
                "❌ Agent build failed — HiroServer · chat",
                error=str(exc),
                exc_info=True,
            )
            raise

    def _summarization_cache_token(self, prefs) -> str:
        """Summarization configuration fingerprint for compiled agent cache keys."""
        from ..domain.preferences import resolve_summarization_llm

        if not prefs.memory.summarization_enabled:
            return "sum:off"
        se = resolve_summarization_llm(
            prefs,
            self._ctx.workspace_path,
            credential_store=self._credential_store,
        )
        if se is None:
            return "sum:none"
        return f"sum:{se.model_id}"

    def _agent_cache_key(self, llm_entry, system_prompt: str, prefs) -> tuple[Any, ...]:
        fp = hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()
        return (
            llm_entry.model_id,
            round(float(llm_entry.temperature), 6),
            int(llm_entry.max_tokens),
            self._summarization_cache_token(prefs),
            fp,
        )

    def _get_or_create_agent(self, llm_entry, system_prompt: str, prefs):
        key = self._agent_cache_key(llm_entry, system_prompt, prefs)
        agent = self._agent_cache.get(key)
        if agent is not None:
            self._agent_cache.move_to_end(key)
            return agent
        assert self._checkpointer is not None
        agent = self._build_agent(
            self._checkpointer,
            self._credential_store,
            llm_entry=llm_entry,
            system_prompt=system_prompt,
            prefs=prefs,
        )
        self._agent_cache[key] = agent
        self._agent_cache.move_to_end(key)
        while len(self._agent_cache) > self._agent_cache_max:
            self._agent_cache.popitem(last=False)
        return agent

    def _load_character_for_channel(self, character_id: str):
        from ..domain.character import default_character_id, load_character_from_disk

        wp = self._ctx.workspace_path
        cid = (character_id or "").strip()
        if not cid:
            cid = default_character_id(wp)
        try:
            return load_character_from_disk(wp, cid)
        except FileNotFoundError:
            fallback = default_character_id(wp)
            log.warning(
                "⚠️ Character folder missing — HiroServer · using default character",
                requested=cid,
                fallback=fallback,
            )
            return load_character_from_disk(wp, fallback)

    def _resolve_thread_character(
        self, msg: UnifiedMessage
    ) -> tuple[str, int, str]:
        """Return (thread_id, channel_id, character_id) for this channel+sender pair."""
        from ..domain.data_store import get_default_user_id
        from ..domain.character import default_character_id
        from ..tools.conversation import ConversationChannelGetTool

        channel_name = f"{msg.routing.channel}:{msg.routing.sender_id}"
        user_id = get_default_user_id(self._ctx.workspace_path)
        channel_result = ConversationChannelGetTool().execute(
            channel_name=channel_name,
            workspace_path=self._ctx.workspace_path,
            user_id=user_id,
        )
        if channel_result.channel is None:
            raise RuntimeError("No conversation channel available for agent thread resolution")
        row = channel_result.channel
        channel_id = int(row["id"])
        character_id = (row.get("character_id") or "").strip()
        if not character_id:
            character_id = default_character_id(self._ctx.workspace_path)
        return str(channel_id), channel_id, character_id

    @property
    def _tts_enabled(self) -> bool:
        """Check if TTS is enabled in workspace preferences."""
        from ..domain.preferences import load_preferences

        prefs = load_preferences(self._ctx.workspace_path)
        return prefs.audio.agent_replies_in_voice

    async def _synthesize_and_send(
        self,
        inbound: UnifiedMessage,
        text_reply: UnifiedMessage,
        text: str,
        *,
        character_voice_models: list[str],
        tts_instructions: str = "",
        tts_voice_by_provider: dict[str, str] | None = None,
    ) -> None:
        """Synthesize speech from the agent's text reply and send a message.voiced event.

        Runs as a fire-and-forget task. On failure, logs the error — the text
        reply has already been delivered so the user is never left without a response.
        """
        try:
            from ..domain.preferences import load_preferences, resolve_character_voice

            prefs = load_preferences(self._ctx.workspace_path)
            peer = comm_peer_label(inbound, self._ctx)

            resolved = resolve_character_voice(
                character_voice_models,
                prefs,
                self._ctx.workspace_path,
                credential_store=self._credential_store,
                tts_instructions=tts_instructions,
                tts_voice_by_provider=tts_voice_by_provider,
            )
            # Voice preset / instructions come from the character (optional); prefs supply default_tts fallback.
            if resolved is None:
                log.warning(
                    f"⚠️ Voice reply skipped — {peer} · no TTS model resolved "
                    "(set character voice_models and/or llm.default_tts)",
                    ref_id=text_reply.routing.id,
                )
                return
            result = await self._tts_service.synthesize(
                text,
                model=resolved.model,
                voice=resolved.voice,
                instructions=resolved.instructions,
            )

            # DEBUG: save MP3 to workspace for manual playback testing
            tts_debug_dir = self._ctx.workspace_path / "tts_debug"
            tts_debug_dir.mkdir(exist_ok=True)
            debug_file = tts_debug_dir / f"{text_reply.routing.id}.mp3"
            debug_file.write_bytes(result.audio_bytes)
            log.debug(
                f"🔧 TTS debug file written — {peer}",
                path=str(debug_file),
            )

            audio_b64 = base64.b64encode(result.audio_bytes).decode()
            voiced_event = UnifiedMessage(
                message_type=MESSAGE_TYPE_EVENT,
                routing=MessageRouting(
                    channel=inbound.routing.channel,
                    direction="outbound",
                    sender_id="server",
                    recipient_id=inbound.routing.sender_id,
                    metadata=inbound.routing.metadata,
                ),
                event=EventPayload(
                    type=EVENT_TYPE_MESSAGE_VOICED,
                    ref_id=text_reply.routing.id,
                    data={
                        "audio": audio_b64,
                        "mime_type": result.mime_type,
                        "duration_ms": result.duration_ms,
                    },
                ),
            )
            await self._comm.enqueue_outbound(voiced_event)
            log.info(
                f"{LOG_OUT} Voiced event enqueued — {peer} · event:{EVENT_TYPE_MESSAGE_VOICED}",
                duration_ms=result.duration_ms,
                mime_type=result.mime_type,
                audio_bytes=len(result.audio_bytes),
                model=result.model,
                voice=result.voice,
                ref_id=text_reply.routing.id,
            )
        except Exception as exc:
            # Graceful degradation: text was already delivered, just log
            peer = comm_peer_label(inbound, self._ctx)
            log.error(
                f"❌ TTS synthesis failed — {peer} · text reply already sent",
                error=str(exc),
                ref_id=text_reply.routing.id,
                exc_info=True,
            )

    async def _process(self, msg: UnifiedMessage) -> None:
        from ..domain.character import effective_character_system_prompt
        from ..domain.preferences import load_preferences, resolve_character_llm

        peer = comm_peer_label(msg, self._ctx)
        thread_id, channel_id, character_id = self._resolve_thread_character(msg)
        config = {"configurable": {"thread_id": thread_id}}

        # Build agent input from all content items first (avoid compiling graphs for empty input).
        parts: list[str] = []
        for item in msg.content:
            if item.content_type == "text":
                if item.body:
                    parts.append(item.body)
            elif "description" in item.metadata:
                desc = item.metadata["description"]
                if item.content_type == "audio":
                    parts.append(desc)
                else:
                    parts.append(f"[{item.content_type}]: {desc}")
            else:
                log.warning(
                    f"⚠️ Skipping content item — {peer} · {item.content_type}",
                    adapter_error=item.metadata.get("adapter_error"),
                    msg_id=msg.routing.id,
                )

        text_body = "\n".join(parts)

        if not text_body:
            adapter_errors = [
                i.metadata["adapter_error"]
                for i in msg.content
                if "adapter_error" in i.metadata
            ]
            log.warning(
                f"{LOG_IN} No usable input — {peer} · {comm_kind(msg)}",
                **comm_extras(
                    msg,
                    content_types=[i.content_type for i in msg.content],
                    adapter_errors=adapter_errors or None,
                ),
            )
            return

        prefs = load_preferences(self._ctx.workspace_path)
        ch = self._load_character_for_channel(character_id)
        system_prompt = effective_character_system_prompt(ch)
        llm_entry = resolve_character_llm(
            ch.llm_models,
            prefs,
            self._ctx.workspace_path,
            credential_store=self._credential_store,
        )
        if llm_entry is None:
            reply = _make_reply(
                msg,
                "The agent is not available — no chat LLM is configured. "
                "Please register an LLM in preferences.json.",
            )
            await self._comm.enqueue_outbound(reply)
            log.info(
                f"{LOG_OUT} Fallback reply enqueued — {peer} · {comm_kind(msg)}",
                **comm_extras(msg, reason="no_chat_llm"),
            )
            return

        try:
            agent = self._get_or_create_agent(llm_entry, system_prompt, prefs)
        except Exception as exc:
            log.error(
                f"❌ Agent build failed for message — {peer} · {comm_kind(msg)}",
                error=str(exc),
                **comm_extras(msg, character_id=character_id, model_id=llm_entry.model_id),
                exc_info=True,
            )
            reply = _make_reply(
                msg,
                "The assistant could not load its model for this conversation. "
                "Check workspace LLM configuration and try again.",
            )
            await self._comm.enqueue_outbound(reply)
            return

        log.info(
            f"{LOG_IN} Agent processing — {peer} · {comm_kind(msg)}",
            **comm_extras(
                msg,
                thread_id=thread_id,
                character_id=character_id,
                model_id=llm_entry.model_id,
                text_preview=text_body[:200],
                body_length=len(text_body),
            ),
        )
        try:
            agent_input = {"messages": [{"role": "user", "content": text_body}]}

            # Log the full conversation state the LLM will see (checkpoint + new message).
            state = await agent.aget_state(config)
            history = state.values.get("messages", []) if state.values else []
            log.debug(
                f"{LOG_IN} Agent invocation context — {peer} · {comm_kind(msg)}",
                **comm_extras(
                    msg,
                    thread_id=thread_id,
                    history_len=len(history),
                    history_summary=[
                        {
                            "role": getattr(m, "type", "?"),
                            "len": len(m.content) if isinstance(m.content, str) else "tool_calls",
                            "preview": (
                                m.content[:80]
                                if isinstance(m.content, str)
                                else str(m.content)[:80]
                            ),
                        }
                        for m in history[-10:]  # last 10 messages for brevity
                    ],
                    new_input=text_body[:200],
                ),
            )

            _t0 = time.perf_counter()
            result = await agent.ainvoke(
                agent_input,
                config=config,
            )
            _elapsed_ms = int((time.perf_counter() - _t0) * 1000)
            raw_reply_content = result["messages"][-1].content
            # LangChain can preserve provider-native content blocks; Hiro replies require text.
            reply_body = _normalize_reply_content(raw_reply_content)
            if not reply_body:
                raise ValueError("agent returned empty reply content")
            log.info(
                f"✅ Agent reply — {peer} · {comm_kind(msg)}",
                **comm_extras(
                    msg,
                    reply_preview=reply_body[:200],
                    output_length=len(reply_body),
                    raw_content_type=_reply_content_type(raw_reply_content),
                    elapsed_ms=_elapsed_ms,
                    thread_id=thread_id,
                ),
            )
        except Exception as exc:
            log.error(
                f"❌ Agent invocation failed — {peer} · {comm_kind(msg)}",
                error=str(exc),
                **comm_extras(msg, thread_id=thread_id),
                exc_info=True,
            )
            reply_body = _FALLBACK_ERROR_BODY

        try:
            reply = _make_reply(msg, reply_body)
        except Exception as exc:
            log.error(
                f"❌ Reply construction failed — {peer} · {comm_kind(msg)}",
                error=str(exc),
                reply_body_type=type(reply_body).__name__,
                **comm_extras(msg, thread_id=thread_id),
                exc_info=True,
            )
            raise

        # Persist the outbound reply to data.db
        try:
            from ..domain.message_store import save_message
            await save_message(
                self._ctx.workspace_path,
                external_id=reply.routing.id,
                channel_id=channel_id,
                sender_type="agent",
                sender_id="server",
                content_type="text",
                body=reply_body,
            )
        except Exception as exc:
            log.warning(
                f"⚠️ Reply save failed — {peer}",
                error=str(exc),
                in_reply_to=msg.routing.id,
                thread_id=thread_id,
            )

        try:
            await self._comm.enqueue_outbound(reply)
        except Exception as exc:
            log.error(
                f"❌ Reply enqueue failed — {comm_peer_label(reply, self._ctx)} · {comm_kind(reply)}",
                error=str(exc),
                **comm_extras(reply, in_reply_to=msg.routing.id, thread_id=thread_id),
                exc_info=True,
            )
            raise
        log.info(
            f"{LOG_OUT} Text reply enqueued — {comm_peer_label(reply, self._ctx)} · {comm_kind(reply)}",
            **comm_extras(
                reply,
                in_reply_to=msg.routing.id,
                thread_id=thread_id,
            ),
        )

        # TTS post-processing: fire-and-forget so it never blocks the next message.
        # Text reply is already delivered — if TTS fails, the user still has the text.
        try:
            per_request = msg.routing.metadata.get("request_voice_reply")
            tts_for_this_msg = per_request if per_request is not None else self._tts_enabled
            if tts_for_this_msg and self._tts_service:
                asyncio.create_task(
                    self._synthesize_and_send(
                        msg,
                        reply,
                        reply_body,
                        character_voice_models=ch.voice_models,
                        tts_instructions=ch.tts_instructions,
                        tts_voice_by_provider=dict(ch.tts_voice_by_provider),
                    ),
                    name=f"tts-{reply.routing.id}",
                )
        except Exception as exc:
            log.error(
                f"❌ TTS scheduling failed — {peer} · text reply already sent",
                error=str(exc),
                ref_id=reply.routing.id,
                **comm_extras(msg, thread_id=thread_id),
                exc_info=True,
            )

    def _log_agent_config(self, credential_store=None) -> None:
        """Log workspace default chat resolution (per-message agent uses character prefs first)."""
        try:
            from ..domain.preferences import load_preferences, resolve_llm

            prefs = load_preferences(self._ctx.workspace_path)
            llm = resolve_llm(
                prefs,
                self._ctx.workspace_path,
                "chat",
                credential_store=credential_store,
            )
            if llm:
                log.info(
                    "✅ Workspace chat default — preferences · "
                    f"{llm.model_id} (characters may override via llm_models)",
                    temperature=llm.temperature,
                    max_tokens=llm.max_tokens,
                )
            else:
                log.error(
                    "❌ No chat LLM configured — HiroServer will reply with fallbacks · preferences\n"
                    "Set llm.default_chat and configure providers (hiro provider add / scan-env)."
                )
        except Exception as exc:
            log.error(
                "❌ Failed to load agent config — preferences",
                error=str(exc),
                exc_info=True,
            )

    async def run(self) -> None:
        """Open the LangGraph checkpointer and drain inbound_queue (agents built per message)."""
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        from ..domain.credential_store import CredentialStore
        from ..domain.db import db_path
        from ..domain.preferences import load_preferences, resolve_llm
        from ..domain.workspace import workspace_id_for_path

        wid = workspace_id_for_path(self._ctx.workspace_path)
        credential_store = (
            CredentialStore(self._ctx.workspace_path, wid) if wid is not None else None
        )
        self._credential_store = credential_store
        self._log_agent_config(credential_store=credential_store)
        db = str(db_path(self._ctx.workspace_path))

        # AsyncSqliteSaver manages its own checkpoint tables inside workspace.db.
        # They coexist with the application tables without conflict.
        async with AsyncSqliteSaver.from_conn_string(db) as checkpointer:
            self._checkpointer = checkpointer
            self._agent_cache.clear()

            prefs = load_preferences(self._ctx.workspace_path)
            probe = (
                resolve_llm(
                    prefs,
                    self._ctx.workspace_path,
                    "chat",
                    credential_store=credential_store,
                )
                if credential_store is not None
                else None
            )
            if probe is None:
                log.warning(
                    "⚠️ AgentManager started — workspace · no default chat LLM (per-channel fallback replies only)",
                    db=db,
                )
            else:
                log.info(
                    "✅ AgentManager started — workspace · per-channel character agents",
                    db=db,
                )
            while True:
                msg: UnifiedMessage = await self._comm.inbound_queue.get()
                try:
                    await self._process(msg)
                except Exception as exc:
                    # Keep the worker alive so one malformed provider response cannot block later messages.
                    log.error(
                        f"❌ Agent message handling failed — {comm_peer_label(msg, self._ctx)} · {comm_kind(msg)}",
                        error=str(exc),
                        **comm_extras(msg),
                        exc_info=True,
                    )
                finally:
                    self._comm.inbound_queue.task_done()
