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
from hirocli.domain.memory_ingest_cursor import advance_cursor, get_cursor
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
async def test_fresh_conversation_counts_the_first_turn(tmp_path) -> None:
    # A wiped/fresh conversation (no cursor): the FIRST turn is windowed, NOT consumed as an
    # un-ingested anchor (the earlier start-from-now bug).
    ensure_data_db(tmp_path)
    ch = create_channel(tmp_path, name="C", character_id="agent-a")
    _msg(tmp_path, ch.id, "u1", "user", "hey there", "2026-07-01T09:00:00+00:00")

    mem = _FakeMemory()
    res = await _ingest(mem, tmp_path, ch.id, n=1, reply_id="a1", reply_text="hi",
                        reply_at="2026-07-01T09:00:05+00:00")

    assert res.facts == 1 and len(mem.calls) == 1
    assert "Misho: hey there" in mem.calls[0]["body"]  # turn 1 is included
    assert get_cursor(tmp_path, ch.id)["last_ingested_id"] == "u1"


@pytest.mark.asyncio
async def test_first_watermark_skips_prior_history_keeps_current_turn(tmp_path) -> None:
    # Pre-existing history but no cursor (memory just enabled on an old chat): only the CURRENT turn
    # is windowed; the old pre-cursor history is skipped (decision A: don't back-fill).
    ensure_data_db(tmp_path)
    ch = create_channel(tmp_path, name="C", character_id="agent-a")
    cid = ch.id
    _msg(tmp_path, cid, "old_u", "user", "old stuff", "2026-07-01T08:00:00+00:00")
    _msg(tmp_path, cid, "old_a", "agent", "old reply", "2026-07-01T08:00:05+00:00")
    _msg(tmp_path, cid, "u_now", "user", "i live in alexandria", "2026-07-01T09:00:00+00:00")

    mem = _FakeMemory()
    res = await _ingest(mem, tmp_path, cid, n=1, reply_id="a_now", reply_text="nice",
                        reply_at="2026-07-01T09:00:05+00:00")

    assert res.facts == 1 and len(mem.calls) == 1
    body = mem.calls[0]["body"]
    assert "alexandria" in body and "old stuff" not in body  # current in, old history skipped
    assert get_cursor(tmp_path, cid)["last_ingested_id"] == "u_now"


@pytest.mark.asyncio
async def test_windows_advance_and_no_reingest(tmp_path) -> None:
    ensure_data_db(tmp_path)
    ch = create_channel(tmp_path, name="C", character_id="agent-a")
    cid = ch.id

    # Turn 1 (fresh): the exchange is windowed and the cursor advances to u1.
    _msg(tmp_path, cid, "u1", "user", "hello", "2026-07-01T09:00:00+00:00")
    mem = _FakeMemory()
    r1 = await _ingest(mem, tmp_path, cid, n=1, reply_id="a1", reply_text="hi",
                       reply_at="2026-07-01T09:00:05+00:00")
    assert r1.facts == 1 and get_cursor(tmp_path, cid)["last_ingested_id"] == "u1"

    # Turn 2: a1 now durable (leading → ignored), u2 arrives, a2 spliced → only u2's window ingests.
    _msg(tmp_path, cid, "a1", "agent", "hi", "2026-07-01T09:00:05+00:00")
    _msg(tmp_path, cid, "u2", "user", "I love pizza", "2026-07-01T09:01:00+00:00")
    mem2 = _FakeMemory()
    r2 = await _ingest(mem2, tmp_path, cid, n=1, reply_id="a2", reply_text="Great!",
                       reply_at="2026-07-01T09:01:05+00:00")
    assert r2.facts == 1 and len(mem2.calls) == 1
    body = mem2.calls[0]["body"]
    assert "I love pizza" in body and "hello" not in body  # u1/a1 already ingested → not repeated
    assert get_cursor(tmp_path, cid)["last_ingested_id"] == "u2"

    # Turn 3: a2 persists (leading agent), no new user turn → nothing to re-ingest.
    _msg(tmp_path, cid, "a2", "agent", "Great!", "2026-07-01T09:01:05+00:00")
    mem3 = _FakeMemory()
    assert (await _ingest(mem3, tmp_path, cid, n=1)).facts == 0
    assert mem3.calls == [] and get_cursor(tmp_path, cid)["last_ingested_id"] == "u2"


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

    # Two complete exchanges pending (sub-N with N=5 → nothing flushes normally). Seed a
    # beginning-watermark cursor (a real conversation gets one on its first turn).
    _msg(tmp_path, cid, "u1", "user", "hello", "2026-07-01T09:00:00+00:00")
    _msg(tmp_path, cid, "a1", "agent", "hi", "2026-07-01T09:00:05+00:00")
    _msg(tmp_path, cid, "u2", "user", "I love pizza", "2026-07-01T09:01:00+00:00")
    _msg(tmp_path, cid, "a2", "agent", "nice", "2026-07-01T09:01:05+00:00")
    advance_cursor(tmp_path, cid, last_ingested_id="", last_ingested_at="")

    mem = _FakeMemory()
    # Not idle yet → the sweep does nothing (a normal N=5 flush wouldn't fire either).
    not_idle = dt.datetime(2026, 7, 1, 9, 3, tzinfo=dt.UTC)
    assert await _sweep(mem, tmp_path, now=not_idle) == 0
    assert mem.calls == []

    # A day later the conversation is idle → the sweep force-flushes the pending sub-N window.
    idle = dt.datetime(2026, 7, 2, 12, 0, tzinfo=dt.UTC)
    n = await _sweep(mem, tmp_path, now=idle)
    assert n == 1 and len(mem.calls) == 1
    assert "Misho: I love pizza" in mem.calls[0]["body"]  # windowed body, user-labelled
    assert get_cursor(tmp_path, cid)["last_ingested_id"] == "u2"  # watermark advanced to last user

    # Idempotent: a second sweep finds nothing pending.
    assert await _sweep(mem, tmp_path, now=idle) == 0
