"""TTS + finalize node group — speech synthesis branch and terminal lifecycle event.

Split out of the old monolithic ``ConversationNodes`` (review §1.5).

- ``tts_gate`` (router) — decide whether to synthesize speech for the reply
- ``tts`` — synthesize and emit ``tts.completed``
- ``finalize`` — emit the terminal ``graph.run.completed`` / ``graph.run.failed`` event

Grouped together because ``finalize`` runs as the terminal node after either branch
(memory_out → tts → finalize, or media_failed → finalize), so they share an exit-edge
contract: ``finalize`` is the single sink.
"""

from __future__ import annotations

import time
from typing import Any

from hiro_commons.log import Logger
from langgraph.types import RetryPolicy, StreamWriter

from ..events import (
    GRAPH_ERROR,
    GRAPH_RUN_COMPLETED,
    GRAPH_RUN_FAILED,
    GRAPH_TTS_COMPLETED,
)
from ..graph_kit import IDENTITY_PEER_KEYS, emit
from ..ledger import graph_logged, observe
from ..node_group import NodeGroup
from ..outcomes import NodeOutcome, emit_outcome
from ..state import GraphState
from .tts_support import build_tts_attachment_and_payload

log = Logger.get("AGENT.GRAPH")


class TTSNodes(NodeGroup):
    """Speech synthesis + terminal lifecycle — constructed from ``AgentServices`` only."""

    _RETRY_POLICIES = {"tts": RetryPolicy(max_attempts=2)}

    def tts_gate(self, state: GraphState) -> str:
        """Decide whether to enter the TTS branch after the reply completes."""
        if not state.get("reply_text"):
            return "finalize"
        if not state.get("request_voice_reply"):
            return "finalize"
        if self.services.tts is None or not self.services.tts.is_available():
            return "finalize"
        return "tts"

    def _resolve_voice(self, state: GraphState, writer: StreamWriter):
        """Load character + resolve TTS voice; return resolved voice or None after observe/emit."""
        from ....domain.character import load_character_from_disk
        from ....domain.preferences import resolve_character_voice

        inbound_id = state.get("inbound_id", "")
        try:
            ch = load_character_from_disk(
                self.services.workspace_path, state.get("character_id", "")
            )
        except FileNotFoundError as exc:
            observe(
                decision=("skipped_no_voice", "character_missing"),
                skipped="character_missing",
                output="audio: skipped character_missing",
            )
            emit(
                writer,
                GRAPH_ERROR,
                {"inbound_id": inbound_id, "node": "tts", "error": str(exc)},
            )
            return None

        prefs = self.prefs.current
        resolved = resolve_character_voice(
            ch.voice_models,
            prefs,
            self.services.workspace_path,
            credential_store=self.services.credentials,
            tts_instructions=ch.tts_instructions,
            tts_voice_by_provider=dict(ch.tts_voice_by_provider),
        )
        if resolved is None:
            observe(
                decision=("skipped_no_voice", "voice_unresolved"),
                skipped="voice_unresolved",
                output="audio: skipped voice_unresolved",
            )
            log.warning(
                "⚠️ tts — %s · no_voice_resolved (set character voice_models / llm.default_tts)",
                inbound_id,
            )
            emit(
                writer,
                GRAPH_ERROR,
                {"inbound_id": inbound_id, "node": "tts", "error": "no_voice_resolved"},
            )
            return None
        return resolved

    @graph_logged(captures={"usage", "decision"})
    async def tts_node(self, state: GraphState, writer: StreamWriter) -> dict[str, Any]:
        """Synthesize speech for ``reply_text`` and emit ``tts.completed``.

        Audio bytes are passed through the event payload as base64 (the same wire shape
        ``message.voiced`` already used today). The persistence subscriber on the
        CommManager side writes the attachment row and the media file from the event.
        """
        text = state.get("reply_text") or ""
        inbound_id = state.get("inbound_id", "")
        observe(input=f"text: {text}" if text else "text: <empty>")
        if not text:
            observe(
                decision=("skipped_no_text", "empty"),
                skipped="empty",
                output="audio: skipped empty",
            )
            return {}

        resolved = self._resolve_voice(state, writer)
        if resolved is None:
            return {}

        t0 = time.perf_counter()
        try:
            result = await self.services.tts.synthesize(  # type: ignore[union-attr]
                text,
                model=resolved.model,
                voice=resolved.voice,
                instructions=resolved.instructions,
            )
        except Exception as exc:
            observe(fail={"code": "tts_failed", "message": str(exc)})
            log.error("❌ tts — %s", inbound_id, error=str(exc), exc_info=True)
            emit(
                writer,
                GRAPH_ERROR,
                {"inbound_id": inbound_id, "node": "tts", "error": str(exc)},
            )
            return {}

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        log.info(
            "✅ tts — %s · bytes=%d · model=%s",
            inbound_id,
            len(result.audio_bytes),
            result.model,
            elapsed_ms=elapsed_ms,
        )

        built = build_tts_attachment_and_payload(
            result,
            resolved,
            text,
            reply_id=state.get("reply_id") or "",
        )
        provider = str(getattr(result, "provider", "") or "")
        usage_counts = built.usage_counts
        emit_outcome(
            writer,
            state,
            NodeOutcome(
                usage={
                    "provider": provider,
                    "model": result.model,
                    "input_tokens": usage_counts["input_tokens"],
                    "tts_chars": len(text),
                    "tts_text_tokens": usage_counts["tts_text_tokens"],
                    "tts_audio_tokens": usage_counts["tts_audio_tokens"],
                    "tts_audio_seconds": usage_counts["tts_audio_seconds"],
                },
                decision=("voiced", provider),
                output=(
                    f"audio: {len(result.audio_bytes)} bytes · duration: {result.duration_ms}ms"
                    f" · voice: {result.voice}"
                ),
                event=(GRAPH_TTS_COMPLETED, built.payload),
                event_identity_keys=IDENTITY_PEER_KEYS,
            ),
        )
        return {"reply_audio": built.attachment}

    @graph_logged(captures={"decision"})
    async def finalize_node(self, state: GraphState, writer: StreamWriter) -> dict[str, Any]:
        """Emit the terminal graph-run lifecycle event.

        The aggregate agent status is about the whole graph run, not a node like
        ``memory_out``. A missing text reply is the first-pass fatal condition;
        everything after a text reply (for example TTS) is degradable.
        """
        inbound_id = state.get("inbound_id", "")
        chat_channel_id = int(state.get("chat_channel_id") or 0)
        reply_id = state.get("reply_id") or ""
        reply_text = state.get("reply_text") or ""
        observe(input=f"reply_id: {reply_id or '<empty>'} · reply: {reply_text}")
        if reply_text and reply_id:
            emit_outcome(
                writer,
                state,
                NodeOutcome(
                    decision=("completed", "ok"),
                    output="run: completed",
                    event=(GRAPH_RUN_COMPLETED, {"reply_id": reply_id}),
                    event_identity_keys=IDENTITY_PEER_KEYS,
                ),
            )
            return {}

        emit_outcome(
            writer,
            state,
            NodeOutcome(
                fail={
                    "code": "reply_generation_failed",
                    "message": "reply generation failed",
                    "decision": "failed",
                },
                event=(
                    GRAPH_RUN_FAILED,
                    {
                        "code": "reply_generation_failed",
                        "message": "I couldn't finish generating a reply.",
                        "node": "finalize",
                    },
                ),
                event_identity_keys=IDENTITY_PEER_KEYS,
            ),
        )
        return {}
