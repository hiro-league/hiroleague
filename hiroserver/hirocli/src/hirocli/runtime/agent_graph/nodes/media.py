"""Media intake node group — ingest, STT, vision, gather, input gate."""

from __future__ import annotations

import time
import uuid
from typing import Any

from hiro_channel_sdk.constants import (
    CONTENT_TYPE_AUDIO,
    CONTENT_TYPE_IMAGE,
    CONTENT_TYPE_TEXT,
)
from hiro_channel_sdk.models import UnifiedMessage
from hiro_commons.log import Logger
from langgraph.types import RetryPolicy, Send, StreamWriter

from ..events import (
    GRAPH_ERROR,
    GRAPH_INGEST_COMPLETED,
    GRAPH_REPLY_COMPLETED,
    GRAPH_STT_COMPLETED,
    GRAPH_VISION_COMPLETED,
)
from ..graph_kit import emit, emit_for, IDENTITY_PEER_KEYS
from ..outcomes import NodeOutcome, emit_outcome
from ..ledger import graph_logged, observe
from ..node_group import NodeGroup
from ..state import (
    AudioItem,
    GraphState,
    ImageItem,
    NodeError,
    SttSend,
    Transcript,
    Vision,
    VisionSend,
)

log = Logger.get("AGENT.GRAPH")


def _audio_item_preview(item: AudioItem) -> str:
    seconds = ""
    duration_ms = item.get("duration_ms")
    if isinstance(duration_ms, (int, float)) and duration_ms > 0:
        seconds = f"; duration_s={duration_ms / 1000:.2f}"
    size = item.get("size")
    size_text = f"; bytes={size}" if isinstance(size, int) and size > 0 else ""
    return f"audio item {item.get('item_index')}; mime={item.get('mime_type')}{size_text}{seconds}"


def _image_item_preview(item: ImageItem) -> str:
    blob = item.get("blob_id") or ""
    return f"image item {item.get('item_index')}" + (f"; blob={blob}" if blob else "")


class MediaNodes(NodeGroup):
    """Stateless intake nodes — constructed from ``AgentServices`` only."""

    # STT/vision both call external providers and benefit from one retry on transient errors.
    _RETRY_POLICIES = {
        "stt": RetryPolicy(max_attempts=2),
        "vision": RetryPolicy(max_attempts=2),
    }

    async def ingest_node(self, state: GraphState, writer: StreamWriter) -> dict[str, Any]:
        """Split the inbound UnifiedMessage into per-modality fan-out inputs.

        Bytes ride on the per-item dicts so they reach the STT/vision Send
        sub-states without polluting parent state. ``audio_items`` etc. are
        cleared by ``gather_node`` so the bytes never enter the long-lived
        checkpoint.
        """
        envelope = state.get("inbound_envelope") or {}
        msg = UnifiedMessage.model_validate(envelope) if envelope else None

        audio_items: list[AudioItem] = []
        image_items: list[ImageItem] = []
        text_inputs: list[str] = []

        if msg is not None:
            voice_input_allowed = bool(state.get("voice_input_allowed", True))
            for idx, item in enumerate(msg.content):
                if item.content_type == CONTENT_TYPE_TEXT:
                    if item.body:
                        text_inputs.append(item.body)
                elif item.content_type == CONTENT_TYPE_AUDIO and voice_input_allowed:
                    audio_items.append(
                        AudioItem(
                            item_index=idx,
                            body=item.body,
                            mime_type=str(item.metadata.get("mime_type", "audio/m4a")),
                            blob_id=item.metadata.get("blob_id"),
                            size=item.metadata.get("size"),
                            duration_ms=item.metadata.get("duration_ms"),
                        )
                    )
                elif item.content_type == CONTENT_TYPE_IMAGE:
                    image_items.append(
                        ImageItem(
                            item_index=idx,
                            body=item.body,
                            blob_id=item.metadata.get("blob_id"),
                        )
                    )
                # Other content types are skipped silently here — gather_node
                # surfaces "no usable input" if everything is dropped.

        log.info(
            "✅ ingest — %s · audio=%d image=%d text=%d",
            state.get("inbound_id", "?"),
            len(audio_items),
            len(image_items),
            len(text_inputs),
        )
        emit_for(
            writer,
            state,
            GRAPH_INGEST_COMPLETED,
            {
                "model_id": state.get("model_id", ""),
                "audio_count": len(audio_items),
                "image_count": len(image_items),
                "text_count": len(text_inputs),
            },
        )
        return {
            "audio_items": audio_items,
            "image_items": image_items,
            "text_inputs": text_inputs,
        }


    @staticmethod
    def dispatch_media(state: GraphState) -> list[Send] | str:
        """Fan out to STT and vision branches, one Send per content item.

        Returns either a list of ``Send`` objects (parallel sub-state branches
        for each media item) or the string ``"gather"`` when there is nothing
        to fan out to. The string return takes the regular edge so the parent
        state is preserved — Sends would otherwise replace state with the
        empty sub-state dict.
        """
        sends: list[Send] = []
        for item in state.get("audio_items", []) or []:
            payload: SttSend = {
                "audio_item": item,
                "inbound_id": state.get("inbound_id", ""),
                "chat_channel_id": state.get("chat_channel_id", 0),
                "routing_metadata": dict(state.get("routing_metadata") or {}),
                "character_id": state.get("character_id", ""),
            }
            sends.append(Send("stt", payload))
        for item in state.get("image_items", []) or []:
            payload: VisionSend = {
                "image_item": item,
                "inbound_id": state.get("inbound_id", ""),
                "chat_channel_id": state.get("chat_channel_id", 0),
                "routing_metadata": dict(state.get("routing_metadata") or {}),
                "character_id": state.get("character_id", ""),
            }
            sends.append(Send("vision", payload))
        if sends:
            return sends
        # No fan-out branches → take the regular edge to gather with full state.
        return "gather"


    @graph_logged(captures={"usage", "decision"}, on_error="degrade")
    async def stt_node(self, sub_state: SttSend, writer: StreamWriter) -> dict[str, Any]:
        """Transcribe one audio item. Runs in parallel branches via Send."""
        item: AudioItem = sub_state["audio_item"]
        inbound_id = sub_state.get("inbound_id", "")
        observe(input=_audio_item_preview(item))
        if self.services.stt is None or not self.services.stt.is_available():
            observe(fail={"code": "stt_unavailable", "message": "STT provider unavailable"})
            err: NodeError = {
                "node": "stt",
                "item_index": item["item_index"],
                "error": "stt_unavailable",
            }
            emit(
            writer, GRAPH_ERROR, {
                "inbound_id": inbound_id, "node": "stt", "error": "stt_unavailable",
            })
            return {"errors": [err]}

        t0 = time.perf_counter()
        try:
            result = await self.services.stt.transcribe(item["body"], mime_type=item["mime_type"])
        except Exception as exc:
            observe(fail={"code": "stt_failed", "message": str(exc)})
            log.error(
                "❌ stt — %s · item=%d", inbound_id, item["item_index"],
                error=str(exc), exc_info=True,
            )
            emit(
            writer, GRAPH_ERROR, {
                "inbound_id": inbound_id, "node": "stt", "error": str(exc),
            })
            err = {"node": "stt", "item_index": item["item_index"], "error": str(exc)}
            return {"errors": [err]}

        text = result.text
        usage = result.usage_metadata or {}
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        # Prefer the provider's reported model/provider; fall back to the service default map.
        model_id = result.model or str(getattr(self.services.stt, "_default_model", "") or "")
        provider = result.provider
        if not provider:
            provider_map = getattr(self.services.stt, "_model_to_provider", {})
            provider_obj = provider_map.get(model_id) if isinstance(provider_map, dict) else None
            if provider_obj is not None:
                provider = str(getattr(provider_obj, "name", "") or "")
        # Record seconds (per-second fallback) AND the token usage (token-based pricing) so the
        # ledger prices via ``estimate_stt_usage_cost``.
        log.info(
            "✅ stt — %s · item=%d", inbound_id, item["item_index"],
            elapsed_ms=elapsed_ms,
            transcript_preview=text[:120],
        )

        result: Transcript = {
            "item_index": item["item_index"],
            "transcript": text,
            "blob_id": item.get("blob_id"),
            "mime_type": item["mime_type"],
            "duration_ms": item.get("duration_ms"),
        }
        emit_outcome(
            writer,
            sub_state,
            NodeOutcome(
                usage={
                    "provider": provider,
                    "model": model_id,
                    "stt_audio_seconds": (float(item.get("duration_ms") or 0) / 1000),
                    "stt_audio_tokens": (int(usage.get("audio_tokens") or 0) or None),
                    "output_tokens": (int(usage.get("output_tokens") or 0) or None),
                },
                decision=("transcribed" if text.strip() else "silence", provider),
                output=f"transcript: {text}" if text.strip() else "transcript: <empty>",
                event=(
                    GRAPH_STT_COMPLETED,
                    {"item_index": item["item_index"], "transcript": text},
                ),
                event_identity_keys=IDENTITY_PEER_KEYS,
            ),
        )
        return {"transcripts": [result]}


    @graph_logged(captures={"decision"}, on_error="degrade")
    async def vision_node(self, sub_state: VisionSend, writer: StreamWriter) -> dict[str, Any]:
        """Describe one image item. Runs in parallel branches via Send."""
        item: ImageItem = sub_state["image_item"]
        inbound_id = sub_state.get("inbound_id", "")
        observe(input=_image_item_preview(item))
        if self.services.vision is None or not self.services.vision.is_available():
            observe(
                decision=("skipped_unsupported", "vision_unavailable"),
                skipped="vision_unavailable",
                output="error: vision_unavailable",
            )
            err: NodeError = {
                "node": "vision",
                "item_index": item["item_index"],
                "error": "vision_unavailable",
            }
            emit(
            writer, GRAPH_ERROR, {
                "inbound_id": inbound_id, "node": "vision", "error": "vision_unavailable",
            })
            return {"errors": [err]}

        t0 = time.perf_counter()
        try:
            description = await self.services.vision.describe(item["body"])
        except Exception as exc:
            observe(
                decision=("provider_error", "exception"),
                error="provider_error",
                output=f"error: {exc}",
            )
            log.error(
                "❌ vision — %s · item=%d", inbound_id, item["item_index"],
                error=str(exc), exc_info=True,
            )
            emit(
            writer, GRAPH_ERROR, {
                "inbound_id": inbound_id, "node": "vision", "error": str(exc),
            })
            err = {"node": "vision", "item_index": item["item_index"], "error": str(exc)}
            return {"errors": [err]}

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        log.info(
            "✅ vision — %s · item=%d", inbound_id, item["item_index"],
            elapsed_ms=elapsed_ms,
            description_preview=description[:120],
        )
        result: Vision = {
            "item_index": item["item_index"],
            "description": description,
        }
        emit_outcome(
            writer,
            sub_state,
            NodeOutcome(
                decision=("described", "image"),
                output=f"description: {description}",
                event=(
                    GRAPH_VISION_COMPLETED,
                    {"item_index": item["item_index"], "description": description},
                ),
                event_identity_keys=IDENTITY_PEER_KEYS,
            ),
        )
        return {"visions": [result]}


    async def gather_node(self, state: GraphState) -> dict[str, Any]:
        """Compose ``user_text`` from text + transcripts + visions in original item order.

        Also clears ``audio_items`` / ``image_items`` so audio/image bytes
        never persist in the long-lived checkpoint.
        """
        ordered: list[tuple[int, str]] = []
        for idx, body in enumerate(state.get("text_inputs", []) or []):
            # Text passthroughs don't carry their original index; preserve
            # arrival order by giving them sortable negative keys.
            ordered.append((-1_000_000 + idx, body))
        for tr in state.get("transcripts", []) or []:
            ordered.append((tr["item_index"], tr["transcript"]))
        for vi in state.get("visions", []) or []:
            ordered.append((vi["item_index"], f"[image]: {vi['description']}"))

        ordered.sort(key=lambda p: p[0])
        text = "\n".join(p for _, p in ordered if p)
        return {
            "user_text": text or None,
            # Drop bytes from state so checkpoint stays small.
            "audio_items": [],
            "image_items": [],
        }


    @staticmethod
    def input_gate(state: GraphState) -> str:
        """Short-circuit when this turn produced no usable input.

        Triggered when ``gather_node`` failed to compose ``user_text`` (typical
        for audio-only inbounds whose STT branches errored). Calling the LLM
        with an unchanged message history burns the full context for nothing
        and tends to either parrot the previous reply or return empty content.
        Route to ``media_failed`` instead, which produces a canned apology.
        """
        user_text = state.get("user_text") or ""
        if user_text.strip():
            return "trim_history"
        return "media_failed"


    @graph_logged(captures={"decision"}, on_error="raise")
    async def media_failed_node(
        self, state: GraphState, writer: StreamWriter
    ) -> dict[str, Any]:
        """Emit a canned reply when this turn yielded no usable user input.

        Reached via ``input_gate`` when ``user_text`` is empty after gather.
        Sets ``reply_text`` / ``reply_id`` and emits ``graph.reply.completed``
        so downstream subscribers persist and send the fallback the same way
        they handle real LLM replies. ``tts_gate`` then decides whether to
        voice the apology based on the original ``request_voice_reply`` flag.
        """
        inbound_id = state.get("inbound_id", "")
        errs = state.get("errors", []) or []
        stt_failed = any(e.get("node") == "stt" for e in errs)
        vision_failed = any(e.get("node") == "vision" for e in errs)

        if stt_failed and vision_failed:
            reply_text = "Sorry, I couldn't process the audio or image. Please try again."
            detail = "stt_and_vision_failed"
        elif stt_failed:
            reply_text = "Sorry, I couldn't understand the audio. Please try again."
            detail = "stt_failed"
        elif vision_failed:
            reply_text = "Sorry, I couldn't process the image. Please try again."
            detail = "vision_failed"
        else:
            reply_text = (
                "Sorry, I didn't catch any content in your message. Please try again."
            )
            detail = "no_content"

        observe(
            decision=("skipped_no_input", detail),
            input=f"errors: {len(errs)}; user_text: <empty>",
            output=f"reply: {reply_text}",
        )

        reply_id = f"reply-{uuid.uuid4()}"
        log.info(
            "⚠️ media_failed — %s · %s · len=%d",
            inbound_id, detail, len(reply_text),
        )
        emit_for(
            writer,
            state,
            GRAPH_REPLY_COMPLETED,
            {
                "thread_id": state.get("thread_id", ""),
                "reply_text": reply_text,
                "reply_id": reply_id,
                "request_voice_reply": bool(state.get("request_voice_reply", False)),
            },
            identity_keys=IDENTITY_PEER_KEYS,
        )
        return {"reply_text": reply_text, "reply_id": reply_id}

