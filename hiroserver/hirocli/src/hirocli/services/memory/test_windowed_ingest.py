"""Windowed batch ingestion controller — integration over a temp data.db + a fake memory facade.

Proves the two things unit tests of the pure planner can't: start-from-now pinning, and that the
watermark read/advance against the real ``messages`` table never re-ingests a turn.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from hirocli.domain.conversation_channel import create_channel
from hirocli.domain.data_store import ensure_data_db
from hirocli.domain.memory_ingest_cursor import get_cursor
from hirocli.domain.message_store import _sync_save
from hirocli.services.memory.windowed_ingest import (
    ingest_pending_windows,
    sweep_idle_conversations,
)


class _FakeMemory:
    """Records ``add`` calls; returns a stored_count of 1 per window."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def add(self, content, *, user_id, run_id, character_id, metadata=None,
                  ledger_sink=None, rebuild_fts=True, trace_label=None):
        self.calls.append({"body": content, "meta": metadata, "rebuild_fts": rebuild_fts})
        return SimpleNamespace(stored_count=1)


def _msg(ws, channel_id, ext, sender, body, at) -> None:
    _sync_save(
        ws, external_id=ext, channel_id=channel_id, user_id=None, sender_type=sender,
        sender_id="x", content_type="text", body=body, metadata=None, created_at=at,
    )


async def _ingest(mem, ws, cid, *, n=1, reply_id="", reply_text="", reply_at=""):
    return await ingest_pending_windows(
        mem, workspace_path=ws, channel_id=cid, user_id=1, run_id="r", character_id="agent-a",
        user_name="Misho", character_name="Aria", window_turns=n, session_gap_minutes=120,
        chunk_min_tokens=1000, current_reply_id=reply_id, current_reply_text=reply_text,
        current_reply_at=reply_at,
    )


@pytest.mark.asyncio
async def test_start_from_now_pins_and_ingests_nothing(tmp_path) -> None:
    ensure_data_db(tmp_path)
    ch = create_channel(tmp_path, name="C", character_id="agent-a")
    _msg(tmp_path, ch.id, "u1", "user", "hello", "2026-07-01T09:00:00+00:00")

    mem = _FakeMemory()
    n = await _ingest(mem, tmp_path, ch.id)  # no cursor yet → start-from-now

    assert n.facts == 0 and n.windows == 0 and mem.calls == []
    cur = get_cursor(tmp_path, ch.id)
    assert cur is not None and cur["last_ingested_id"] == "u1"  # pinned to latest, nothing ingested


@pytest.mark.asyncio
async def test_windows_ingest_advance_and_no_reingest(tmp_path) -> None:
    ensure_data_db(tmp_path)
    ch = create_channel(tmp_path, name="C", character_id="agent-a")
    cid = ch.id

    # Turn 1: current user durable, start-from-now pins to u1.
    _msg(tmp_path, cid, "u1", "user", "hello", "2026-07-01T09:00:00+00:00")
    mem = _FakeMemory()
    assert (await _ingest(mem, tmp_path, cid)).facts == 0

    # Turn 2: u1's reply (a1) is now durable, and the new user turn u2 arrives; a2 is the current
    # reply (not durable yet) → spliced.
    _msg(tmp_path, cid, "a1", "agent", "hi there", "2026-07-01T09:00:30+00:00")
    _msg(tmp_path, cid, "u2", "user", "I love pizza", "2026-07-01T09:01:00+00:00")
    n = await _ingest(mem, tmp_path, cid, n=1, reply_id="a2", reply_text="Great!",
                      reply_at="2026-07-01T09:01:30+00:00")

    assert n.facts == 1 and n.triggers == ("count",) and len(mem.calls) == 1
    call = mem.calls[0]
    assert call["meta"]["prerendered"] is True and call["meta"]["message_id"] == "u2"
    assert "Misho: I love pizza" in call["body"] and "Aria: Great!" in call["body"]
    assert "hi there" not in call["body"]  # a1 is a leading already-ingested reply → ignored
    assert get_cursor(tmp_path, cid)["last_ingested_id"] == "u2"

    # Turn 3: a2 finally persists (leading agent), no new user turn → nothing to re-ingest.
    _msg(tmp_path, cid, "a2", "agent", "Great!", "2026-07-01T09:01:30+00:00")
    mem2 = _FakeMemory()
    assert (await _ingest(mem2, tmp_path, cid, n=1)).facts == 0
    assert mem2.calls == []  # the already-ingested u2/a2 window is never ingested again
    assert get_cursor(tmp_path, cid)["last_ingested_id"] == "u2"  # watermark unchanged


async def _sweep(mem, ws, *, hours=12, now):
    return await sweep_idle_conversations(
        mem, workspace_path=ws, idle_flush_hours=hours, window_turns=5, session_gap_minutes=120,
        chunk_min_tokens=1000, user_name="Misho", now=now,
    )


@pytest.mark.asyncio
async def test_idle_sweep_flushes_subn_pending(tmp_path) -> None:
    ensure_data_db(tmp_path)
    ch = create_channel(tmp_path, name="C", character_id="agent-a")
    cid = ch.id

    # Pin start-from-now to u1, then leave a complete but sub-N exchange (u2/a2) pending.
    _msg(tmp_path, cid, "u1", "user", "hello", "2026-07-01T09:00:00+00:00")
    mem = _FakeMemory()
    assert (await _ingest(mem, tmp_path, cid)).facts == 0
    _msg(tmp_path, cid, "a1", "agent", "hi", "2026-07-01T09:00:30+00:00")
    _msg(tmp_path, cid, "u2", "user", "I love pizza", "2026-07-01T09:01:00+00:00")
    _msg(tmp_path, cid, "a2", "agent", "nice", "2026-07-01T09:01:30+00:00")

    # Not idle yet (2 min later) → the sweep does nothing; a normal N=5 flush wouldn't fire either.
    not_idle = dt.datetime(2026, 7, 1, 9, 3, tzinfo=dt.UTC)
    assert await _sweep(mem, tmp_path, now=not_idle) == 0
    assert mem.calls == [] and get_cursor(tmp_path, cid)["last_ingested_id"] == "u1"

    # A day later the conversation is idle → the sweep force-flushes the sub-N window.
    idle = dt.datetime(2026, 7, 2, 12, 0, tzinfo=dt.UTC)
    n = await _sweep(mem, tmp_path, now=idle)
    assert n == 1 and len(mem.calls) == 1
    assert "Misho: I love pizza" in mem.calls[0]["body"]  # windowed body, user-labelled
    assert get_cursor(tmp_path, cid)["last_ingested_id"] == "u2"  # watermark advanced

    # Idempotent: a second sweep finds nothing pending (a2 is a leading already-ingested reply).
    assert await _sweep(mem, tmp_path, now=idle) == 0
