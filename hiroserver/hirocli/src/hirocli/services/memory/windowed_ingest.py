"""Windowed batch ingestion controller (data.db + planner + memory facade).

The I/O layer that wraps the pure :mod:`windowing` planner: read the pending durable turns after a
conversation's memory watermark, splice the current (not-yet-durable) reply, plan the windows, and
ingest each as one two-speaker episode — advancing the watermark past exactly what was ingested.

Kept separate from the ``memory_out`` node so this orchestration is unit-testable with a fake
memory facade + a temp data.db (see ``test_windowed_ingest.py``). The node just gathers the values
from graph state/prefs and calls :func:`ingest_pending_windows`.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hiro_commons.log import Logger

from hirocli.domain.memory_ingest_cursor import advance_cursor, get_cursor
from hirocli.domain.message_store import list_messages

from .windowing import WinTurn, plan_windows

log = Logger.get("SVC.MEMORY.WINDOWED_INGEST")


@dataclass(frozen=True)
class WindowIngestResult:
    """Outcome of a windowed-ingest pass, surfaced for observability/tuning: total facts learned
    and the flush trigger of each ingested window (``count`` / ``session_gap`` / ``size`` /
    ``idle``), in order. ``windows`` is the count. Empty on a no-op (start-from-now, nothing
    pending, or a still-accumulating sub-N batch)."""

    facts: int = 0
    triggers: tuple[str, ...] = field(default_factory=tuple)

    @property
    def windows(self) -> int:
        return len(self.triggers)


def _rows_to_turns(rows: list[dict[str, Any]]) -> list[WinTurn]:
    """Map durable message rows (oldest-first) to planner turns. Any non-user sender (agent /
    assistant / system) is the ``agent`` side for windowing purposes."""
    return [
        WinTurn(
            external_id=str(r.get("external_id") or ""),
            role="user" if str(r.get("sender_type") or "") == "user" else "agent",
            text=str(r.get("body") or ""),
            created_at=str(r.get("created_at") or ""),
        )
        for r in rows
    ]


async def ingest_pending_windows(
    memory: Any,
    *,
    workspace_path: Path,
    channel_id: int,
    user_id: int,
    run_id: str,
    character_id: str,
    user_name: str,
    character_name: str,
    window_turns: int,
    session_gap_minutes: int,
    chunk_min_tokens: int,
    current_reply_id: str,
    current_reply_text: str,
    current_reply_at: str,
    ledger_sink: Any | None = None,
    force_flush: bool = False,
) -> WindowIngestResult:
    """Ingest whatever complete windows are now pending for ``channel_id``; return a
    :class:`WindowIngestResult` (facts + per-window flush triggers for observability/tuning).

    Watermark is the last USER message (a durable ``(created_at, external_id)`` compound cursor).
    On an absent cursor we "start from now" — pin the watermark to the latest durable message and
    ingest nothing historical (decision A). Otherwise we read the pending durable turns, splice the
    current reply (so the current exchange completes with no lag), plan windows, ingest each, and
    advance the watermark PER WINDOW — so a mid-loop failure leaves earlier windows committed and
    retries the rest, never re-ingesting."""
    cursor = get_cursor(workspace_path, channel_id)

    # First-ever watermark for this conversation. Decision A is "don't back-fill an EXISTING
    # conversation's old history" — NOT "skip the current turn". So pin the watermark to the message
    # BEFORE the current turn's user message (``rows[-1]`` is the just-arrived user message; its
    # reply isn't durable yet), then fall through and window the current turn normally. A fresh /
    # wiped conversation (only the current turn exists) gets an empty watermark, so turn 1 is
    # counted — not consumed as an un-ingested anchor (the earlier start-from-now bug).
    if cursor is None:
        rows = await list_messages(workspace_path, channel_id, limit=None)
        if not rows:
            return WindowIngestResult()
        prior = rows[-2] if len(rows) >= 2 else None
        wm_id = str(prior.get("external_id") or "") if prior else ""
        wm_at = str(prior.get("created_at") or "") if prior else ""
        advance_cursor(workspace_path, channel_id, last_ingested_id=wm_id, last_ingested_at=wm_at)
        cursor = {"last_ingested_id": wm_id, "last_ingested_at": wm_at}
        log.info(
            "🧭 memory windowing — first watermark · channel=%s · skip_prior_before=%s",
            channel_id,
            wm_id or "(none — fresh conversation)",
        )

    rows = await list_messages(
        workspace_path,
        channel_id,
        after=str(cursor.get("last_ingested_at") or ""),
        after_id=str(cursor.get("last_ingested_id") or ""),
        limit=None,
    )
    turns = _rows_to_turns(rows)
    # Splice the current reply (persisted downstream on reply.completed, so not durable here yet) to
    # complete the current exchange with no lag. Dedup in case persistence already raced it in.
    rid = (current_reply_id or "").strip()
    if rid and current_reply_text and not any(t.external_id == rid for t in turns):
        turns.append(WinTurn(rid, "agent", current_reply_text, current_reply_at))

    # graphiti_core's token estimator drives the chunk guard (same one the corpus loader uses).
    from graphiti_core.utils.content_chunking import estimate_tokens

    windows = plan_windows(
        turns,
        window_turns=window_turns,
        session_gap_minutes=session_gap_minutes,
        chunk_min_tokens=chunk_min_tokens,
        user_name=user_name,
        character_name=character_name,
        estimate_tokens=estimate_tokens,
        # Idle sweep forces the trailing sub-N window out (an abandoned conversation).
        flush_all=force_flush,
    )
    if not windows:
        return WindowIngestResult()

    total_facts = 0
    triggers: list[str] = []
    last_index = len(windows) - 1
    for index, window in enumerate(windows):
        result = await memory.add(
            window.body,
            user_id=user_id,
            run_id=run_id,
            character_id=character_id,
            metadata={
                # Provenance anchor = the window's last user message id (episode uuid == point_id).
                "message_id": window.episode_uuid,
                # Last-turn time drives valid_at / cross-window supersession (see design § temporal).
                "timestamp": window.reference_time,
                # Body is a pre-rendered two-speaker transcript → don't re-prefix a speaker.
                "prerendered": True,
                "source": "conversation",
                # Speaker names → bind {user}/{character} in the extraction clause so the extractor
                # knows which labelled speaker is the human vs the assistant (roles are explicit).
                "user_name": user_name,
                "character_name": character_name,
            },
            ledger_sink=ledger_sink,
            # Rebuild the Kuzu FTS index once, after the last window (avoids a checkpoint per window
            # when a backlog flushes several at once).
            rebuild_fts=(index == last_index),
        )
        window_facts = int(getattr(result, "stored_count", 0) or 0)
        total_facts += window_facts
        triggers.append(window.trigger)
        # Per-window telemetry for tuning window_turns / session_gap_minutes: which trigger closed
        # this window, how many exchanges it held, and how many facts it produced.
        log.info(
            "✅ memory window — ch=%s · trigger=%s · exchanges=%d · facts=%d",
            channel_id,
            window.trigger,
            window.exchange_count,
            window_facts,
        )
        # Advance only AFTER a window is ingested → a crash never skips a window.
        advance_cursor(
            workspace_path,
            channel_id,
            last_ingested_id=window.watermark_id,
            last_ingested_at=window.watermark_at,
        )
    return WindowIngestResult(facts=total_facts, triggers=tuple(triggers))


async def sweep_idle_conversations(
    memory: Any,
    *,
    workspace_path: Path,
    idle_flush_hours: int,
    window_turns: int,
    session_gap_minutes: int,
    chunk_min_tokens: int,
    user_name: str,
    now: dt.datetime | None = None,
    ledger_sink: Any | None = None,
) -> int:
    """Backstop for abandoned conversations: flush the pending (sub-N) turns of any conversation
    idle longer than ``idle_flush_hours`` so its memories still land even though the user never
    returned to trigger a normal flush. Runs out-of-band (a periodic sweep), so there is no current
    reply to splice; ``force_flush=True`` pushes the trailing partial window out. Returns total
    facts stored. Per-channel failures are logged and skipped — one bad channel never aborts the
    sweep."""
    from hirocli.domain.character import get_character_name
    from hirocli.domain.conversation_channel import _get_channel_by_id
    from hirocli.domain.memory import resolve_memory_user_id
    from hirocli.domain.memory_ingest_cursor import list_idle_pending_channels

    cutoff = (now or dt.datetime.now(dt.UTC)) - dt.timedelta(hours=max(1, int(idle_flush_hours)))
    channel_ids = list_idle_pending_channels(workspace_path, idle_before=cutoff.isoformat())
    total_facts = 0
    for channel_id in channel_ids:
        channel = _get_channel_by_id(workspace_path, channel_id)
        if channel is None:
            continue
        try:
            total_facts += (await ingest_pending_windows(
                memory,
                workspace_path=workspace_path,
                channel_id=channel_id,
                user_id=resolve_memory_user_id(
                    data_user_id=channel.user_id, workspace_path=workspace_path
                ),
                run_id=str(channel_id),
                character_id=channel.character_id,
                user_name=user_name,
                character_name=get_character_name(workspace_path, channel.character_id),
                window_turns=window_turns,
                session_gap_minutes=session_gap_minutes,
                chunk_min_tokens=chunk_min_tokens,
                current_reply_id="",
                current_reply_text="",
                current_reply_at="",
                ledger_sink=ledger_sink,
                force_flush=True,
            )).facts
        except Exception:
            log.warning(
                "⚠️ memory idle sweep — channel %s failed (skipped)", channel_id, exc_info=True
            )
    if channel_ids:
        log.info(
            "✅ memory idle sweep — swept %d idle conversation(s) · facts=%d",
            len(channel_ids),
            total_facts,
        )
    return total_facts


__all__ = ["WindowIngestResult", "ingest_pending_windows", "sweep_idle_conversations"]
