"""TTS + finalize node group — speech synthesis branch and terminal lifecycle event.

Split out of the old monolithic ``ConversationNodes`` (review §1.5).

- ``tts_gate`` (router) — decide whether to synthesize speech for the reply
- ``tts`` — synthesize and emit ``tts.completed``

Phase 7b step 5: the voice is a voice profile (``prefs.voice``): the character's voice profiles in
order (the first whose provider has a key), else ``voice.hiro_profile``; none → no voice reply. It is
spoken by ``services/voice`` (PCM) and encoded MP3 for the app (iPhones can't play OGG/Opus).
- ``finalize`` — emit the terminal ``graph.run.completed`` / ``graph.run.failed`` event

Grouped together because ``finalize`` runs as the terminal node after either branch
(memory_out → tts → finalize, or media_failed → finalize), so they share an exit-edge
contract: ``finalize`` is the single sink.
"""

from __future__ import annotations

import asyncio
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
        """Decide whether to enter the TTS branch after the reply completes.

        Kept as an instance method (vs the other routers' ``@staticmethod`` style) because whether a
        voice resolves is a *runtime* check on the live preferences + keys (Phase 7b step 5: a voice
        profile of the character's, else Hiro's own), so it can flip across turns without a rebuild.
        """
        if not state.get("reply_text"):
            return "finalize"
        if not state.get("request_voice_reply"):
            return "finalize"
        if self._voice_for(state.get("character_id", "")) is None:
            return "finalize"
        return "tts"

    def _voice_for(self, character_id: str):
        """The voice profile the character speaks with now, or None (no voice reply)."""
        from ....domain.character import load_character_from_disk
        from ....domain.preferences import resolve_character_voice

        prefs = self.prefs.current
        try:
            voice_ids = load_character_from_disk(self.services.workspace_path, character_id).voice_profiles
        except FileNotFoundError:
            voice_ids = []  # the character's gone: Hiro's own voice still speaks
        return resolve_character_voice(
            voice_ids,
            prefs,
            self.services.workspace_path,
            credential_store=self.services.credentials,
        )

    def _resolve_voice(self, state: GraphState, writer: StreamWriter):
        """Resolve the reply's voice profile; return it, or None after observe/emit."""
        inbound_id = state.get("inbound_id", "")
        resolved = self._voice_for(state.get("character_id", ""))
        if resolved is None:
            observe(
                decision=("skipped_no_voice", "voice_unresolved"),
                skipped="voice_unresolved",
                output="audio: skipped voice_unresolved",
            )
            log.warning(
                "⚠️ tts — %s · no_voice_resolved (set a character voice profile or voice.hiro_profile)",
                inbound_id,
            )
            emit(
                writer,
                GRAPH_ERROR,
                {"inbound_id": inbound_id, "node": "tts", "error": "no_voice_resolved"},
            )
            return None
        return resolved

    @graph_logged(captures={"usage", "decision"}, on_error="degrade")
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

        from ....services.voice import audio, engine

        profile = resolved.profile
        t0 = time.perf_counter()
        try:
            speech = await engine.synthesize(self.services.workspace_path, profile, text)
            mp3 = await asyncio.to_thread(audio.to_mp3, speech.pcm, speech.rate)
        except Exception as exc:
            observe(fail={"code": "tts_failed", "message": str(exc)})
            log.error(
                "❌ tts — %s · %s · %s", inbound_id, profile.label, profile.model, error=str(exc), exc_info=True
            )
            emit(
                writer,
                GRAPH_ERROR,
                {"inbound_id": inbound_id, "node": "tts", "error": str(exc)},
            )
            return {}

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        log.info(
            "✅ tts — %s · %s · bytes=%d · model=%s",
            inbound_id,
            profile.label,
            len(mp3),
            profile.model,
            elapsed_ms=elapsed_ms,
            voice_profile=resolved.profile_id,
        )

        built = build_tts_attachment_and_payload(
            mp3,
            speech,
            profile,
            text,
            reply_id=state.get("reply_id") or "",
        )
        provider = profile.provider
        usage_counts = built.usage_counts
        emit_outcome(
            writer,
            state,
            NodeOutcome(
                usage={
                    "provider": provider,
                    "model": profile.model_name,
                    "input_tokens": usage_counts["input_tokens"],
                    "tts_chars": len(text),
                    "tts_text_tokens": usage_counts["tts_text_tokens"],
                    "tts_audio_tokens": usage_counts["tts_audio_tokens"],
                    "tts_audio_seconds": usage_counts["tts_audio_seconds"],
                },
                decision=("voiced", provider),
                output=(
                    f"audio: {len(mp3)} bytes · duration: {built.payload['duration_ms']}ms"
                    f" · voice: {profile.voice} ({resolved.profile_id})"
                ),
                event=(GRAPH_TTS_COMPLETED, built.payload),
                event_identity_keys=IDENTITY_PEER_KEYS,
            ),
        )
        return {"reply_audio": built.attachment}

    @graph_logged(captures={"decision"}, on_error="raise")
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
