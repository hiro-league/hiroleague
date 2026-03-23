"""AgentManager — LLM agent worker for hirocli.

Responsibilities:
  - Reads inbound messages from CommunicationManager.inbound_queue.
  - Builds agent input from text ContentItems and from metadata["description"]
    on non-text items (audio transcripts, image descriptions set by adapters).
  - Skips messages that yield no input text after checking both sources.
  - Passes each message to a LangChain v1 create_agent instance.
  - Maintains per-conversation persistent memory keyed by conversation_channels.id
    (a UUID) using LangGraph's AsyncSqliteSaver checkpointer backed by workspace.db.
  - Constructs a reply UnifiedMessage and places it on the outbound queue.
  - On LLM errors, enqueues a human-readable fallback reply instead.
"""

from __future__ import annotations

import asyncio
import base64
import time
from typing import TYPE_CHECKING

from hiro_channel_sdk.constants import EVENT_TYPE_MESSAGE_VOICED, MESSAGE_TYPE_EVENT
from hiro_channel_sdk.models import ContentItem, EventPayload, MessageRouting, UnifiedMessage
from hiro_commons.log import Logger

if TYPE_CHECKING:
    from ..services.tts.service import TTSService
    from .communication_manager import CommunicationManager
    from .server_context import ServerContext

log = Logger.get("AGENT")

_FALLBACK_ERROR_BODY = (
    "Sorry, I encountered an error processing your message. Please try again."
)


def _make_reply(inbound: UnifiedMessage, body: str) -> UnifiedMessage:
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
        self._agent = None  # built inside run() once the async checkpointer is ready

    def _build_agent(self, checkpointer):
        """Build the LangChain agent from preferences.  Returns None if no chat LLM is configured."""
        from ..domain.preferences import load_preferences, resolve_llm

        prefs = load_preferences(self._ctx.workspace_path)
        llm_entry = resolve_llm(prefs, "chat")
        if llm_entry is None:
            log.error(
                "⚠️  No chat LLM configured in preferences.json. "
                "The agent cannot process messages until an LLM is registered. "
                "Edit preferences.json in your workspace directory to add one."
            )
            return None

        try:
            from langchain.agents import create_agent
            from langchain.chat_models import init_chat_model

            from ..domain.agent_config import load_system_prompt
            from ..tools import all_tools
            from ..tools.langchain_adapter import to_langchain_list

            system_prompt = load_system_prompt(self._ctx.workspace_path)
            tools = to_langchain_list(all_tools())

            log.fineinfo(
                "Building agent",
                model=llm_entry.model,
                provider=llm_entry.provider,
                temperature=llm_entry.temperature,
                max_tokens=llm_entry.max_tokens,
                tools=len(tools),
            )

            model = init_chat_model(
                model=llm_entry.model,
                model_provider=llm_entry.provider,
                temperature=llm_entry.temperature,
                max_tokens=llm_entry.max_tokens,
            )

            return create_agent(
                model=model,
                tools=tools,
                system_prompt=system_prompt,
                checkpointer=checkpointer,
            )
        except Exception as exc:
            log.error("Error building agent", error=str(exc), exc_info=True)
            raise

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
    ) -> None:
        """Synthesize speech from the agent's text reply and send a message.voiced event.

        Runs as a fire-and-forget task. On failure, logs the error — the text
        reply has already been delivered so the user is never left without a response.
        """
        try:
            from ..domain.preferences import load_preferences, resolve_voice

            voice = resolve_voice(load_preferences(self._ctx.workspace_path))
            if not voice:
                return

            result = await self._tts_service.synthesize(
                text,
                model=voice.model,
                voice=voice.voice,
                instructions=voice.instructions,
            )

            # DEBUG: save MP3 to workspace for manual playback testing
            tts_debug_dir = self._ctx.workspace_path / "tts_debug"
            tts_debug_dir.mkdir(exist_ok=True)
            debug_file = tts_debug_dir / f"{text_reply.routing.id}.mp3"
            debug_file.write_bytes(result.audio_bytes)
            log.debug("TTS debug file saved", path=str(debug_file))

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
                "TTS voiced event enqueued",
                ref_id=text_reply.routing.id,
                model=result.model,
                voice=result.voice,
                audio_bytes=len(result.audio_bytes),
                duration_ms=result.duration_ms,
            )
        except Exception as exc:
            # Graceful degradation: text was already delivered, just log
            log.error(
                "TTS synthesis failed — text reply already sent",
                ref_id=text_reply.routing.id,
                error=str(exc),
                exc_info=True,
            )

    def _resolve_thread_id(self, msg: UnifiedMessage) -> tuple[str, int]:
        """Return (thread_id, channel_id) for this channel+sender pair.

        The channel name used as the lookup key is channel:sender_id so that
        each unique sender on each plugin channel gets its own persistent thread.
        If the requested channel does not exist, the seeded General channel is used.
        thread_id is str(channel.id) — LangGraph uses it as a string key.
        """
        from ..tools.conversation import ConversationChannelGetTool

        channel_name = f"{msg.routing.channel}:{msg.routing.sender_id}"
        channel_result = ConversationChannelGetTool().execute(
            channel_name=channel_name,
            workspace_path=self._ctx.workspace_path,
        )
        if channel_result.channel is None:
            raise RuntimeError("No conversation channel available for agent thread resolution")
        channel_id = int(channel_result.channel["id"])
        return str(channel_id), channel_id

    async def _process(self, msg: UnifiedMessage) -> None:
        if self._agent is None:
            reply = _make_reply(
                msg,
                "The agent is not available — no chat LLM is configured. "
                "Please register an LLM in preferences.json.",
            )
            await self._comm.enqueue_outbound(reply)
            return

        device = msg.routing.metadata.get("device_name", msg.routing.sender_id)
        thread_id, channel_id = self._resolve_thread_id(msg)
        config = {"configurable": {"thread_id": thread_id}}

        # Build agent input from all content items.
        # Audio transcripts are treated as canonical user text (the user spoke
        # these words) — no prefix, so the agent reasons about what was said,
        # not about the fact that it was audio.
        # Other non-text items (image, etc.) keep a descriptive prefix.
        parts = []
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
                    "Skipping content item — no description available",
                    device=device,
                    content_type=item.content_type,
                    adapter_error=item.metadata.get("adapter_error"),
                    msg_id=msg.routing.id,
                )

        text_body = "\n".join(parts)

        if not text_body:
            log.warning(
                "Ignoring message with no usable text input",
                device=device,
                msg_id=msg.routing.id,
                content_types=[i.content_type for i in msg.content],
                adapter_errors=[
                    i.metadata["adapter_error"]
                    for i in msg.content
                    if "adapter_error" in i.metadata
                ],
            )
            return

        log.info(
            "Processing message",
            device=device,
            msg_id=msg.routing.id,
            thread=thread_id,
            text_preview=text_body[:200],
            body_length=len(text_body),
        )
        try:
            agent_input = {"messages": [{"role": "user", "content": text_body}]}

            # Log the full conversation state the LLM will see (checkpoint + new message).
            state = await self._agent.aget_state(config)
            history = state.values.get("messages", []) if state.values else []
            log.debug(
                "Agent invocation context",
                device=device,
                thread=thread_id,
                history_len=len(history),
                history_summary=[
                    {
                        "role": getattr(m, "type", "?"),
                        "len": len(m.content) if isinstance(m.content, str) else "tool_calls",
                        "preview": (m.content[:80] if isinstance(m.content, str) else str(m.content)[:80]),
                    }
                    for m in history[-10:]  # last 10 messages for brevity
                ],
                new_input=text_body[:200],
            )

            _t0 = time.perf_counter()
            result = await self._agent.ainvoke(
                agent_input,
                config=config,
            )
            _elapsed_ms = int((time.perf_counter() - _t0) * 1000)
            reply_body: str = result["messages"][-1].content
            log.info(
                "Agent replied",
                device=device,
                thread=thread_id,
                reply_preview=reply_body[:200],
                output_length=len(reply_body),
                elapsed_ms=_elapsed_ms,
            )
        except Exception as exc:
            log.error(
                "Agent invocation error",
                device=device,
                thread=thread_id,
                error=str(exc),
                exc_info=True,
            )
            reply_body = _FALLBACK_ERROR_BODY

        reply = _make_reply(msg, reply_body)

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
                "Reply persistence failed (non-fatal)",
                error=str(exc),
                thread=thread_id,
            )

        await self._comm.enqueue_outbound(reply)
        log.info(
            "Agent reply enqueued",
            device=device,
            in_reply_to=msg.routing.id,
            thread=thread_id,
        )

        # TTS post-processing: fire-and-forget so it never blocks the next message.
        # Text reply is already delivered — if TTS fails, the user still has the text.
        per_request = msg.routing.metadata.get("request_voice_reply")
        tts_for_this_msg = per_request if per_request is not None else self._tts_enabled
        if tts_for_this_msg and self._tts_service:
            asyncio.create_task(
                self._synthesize_and_send(msg, reply, reply_body),
                name=f"tts-{reply.routing.id}",
            )

    def _log_agent_config(self) -> None:
        """Log the agent model configuration from preferences.

        Absorbed from server_process.py — this is an AgentManager concern.
        """
        try:
            from ..domain.preferences import load_preferences, resolve_llm
            prefs = load_preferences(self._ctx.workspace_path)
            llm = resolve_llm(prefs, "chat")
            if llm:
                log.info(
                    "AI Agent config loaded from preferences",
                    model=llm.model,
                    provider=llm.provider,
                    temperature=llm.temperature,
                    max_tokens=llm.max_tokens,
                )
            else:
                log.error(
                    "No chat LLM configured. The server will run but the agent "
                    "cannot process messages. Register at least one LLM in "
                    "preferences.json (in your workspace directory)."
                )
        except Exception as exc:
            log.error("Failed to load agent config from preferences", error=str(exc))

    async def run(self) -> None:
        """Build the agent with a persistent SQLite checkpointer then drain inbound_queue."""
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        from ..domain.db import db_path

        self._log_agent_config()
        db = str(db_path(self._ctx.workspace_path))

        # AsyncSqliteSaver manages its own checkpoint tables inside workspace.db.
        # They coexist with the application tables without conflict.
        async with AsyncSqliteSaver.from_conn_string(db) as checkpointer:
            self._agent = self._build_agent(checkpointer)
            if self._agent is None:
                log.warning("⚠️ AgentManager started WITHOUT an agent — messages will get a 'not configured' reply")
            else:
                log.info("✅ AgentManager started", db=db)
            while True:
                msg: UnifiedMessage = await self._comm.inbound_queue.get()
                try:
                    await self._process(msg)
                finally:
                    self._comm.inbound_queue.task_done()
