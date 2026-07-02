"""Windowed batch ingestion planner — the correctness gate.

Covers: the three flush triggers (count / session-gap / size), the turn-granular chunk guard,
incomplete/leading-agent handling, N-change safety, and no-re-ingestion across a simulated
watermark advance.
"""

from __future__ import annotations

from hirocli.services.memory.windowing import WinTurn, plan_windows

# token≈char estimator so chunk tests are easy to reason about; big budget disables the size trigger.
_EST = len
_BIG = 10_000


def _turn(seq: int, role: str, *, minute: int = 0, text: str = "hi") -> WinTurn:
    return WinTurn(
        external_id=f"{role[0]}{seq}",
        role=role,
        text=text,
        created_at=f"2026-07-01T09:{minute:02d}:00+00:00",
    )


def _exchanges(n: int, *, start_min: int = 0, step: int = 1, text: str = "hi") -> list[WinTurn]:
    """n back-to-back complete exchanges (user+agent), one minute apart by default."""
    turns: list[WinTurn] = []
    for i in range(1, n + 1):
        m = start_min + (i - 1) * step
        turns.append(_turn(i, "user", minute=m, text=text))
        turns.append(_turn(i, "agent", minute=m, text=text))
    return turns


def _plan(turns, *, n=2, gap=120, chunk=_BIG):
    return plan_windows(
        turns,
        window_turns=n,
        session_gap_minutes=gap,
        chunk_min_tokens=chunk,
        user_name="Misho",
        character_name="Aria",
        estimate_tokens=_EST,
    )


def test_count_trigger_and_anchors() -> None:
    wins = _plan(_exchanges(2), n=2)
    assert len(wins) == 1
    w = wins[0]
    assert w.trigger == "count"
    assert w.exchange_count == 2
    # Provenance/watermark anchor = the window's LAST user message; reference_time = last turn.
    assert w.episode_uuid == "u2" and w.watermark_id == "u2"
    assert w.reference_time == "2026-07-01T09:01:00+00:00"  # last (agent) turn
    assert w.watermark_at == "2026-07-01T09:01:00+00:00"  # last user turn
    # Body carries both speakers, labelled + timestamped; the assistant carries the "(AI)" marker.
    assert "Misho:" in w.body and "Aria (AI):" in w.body and "[2026-07-01 09:00]" in w.body


def test_under_n_stays_pending() -> None:
    # One complete exchange with N=2 → nothing flushed (waits for more / idle sweep).
    assert _plan(_exchanges(1), n=2) == []


def test_flush_all_forces_leftover_window() -> None:
    # The idle sweep forces a sub-N leftover out with an "idle" trigger.
    assert _plan(_exchanges(1), n=2) == []
    forced = plan_windows(
        _exchanges(1), window_turns=2, session_gap_minutes=120, chunk_min_tokens=_BIG,
        user_name="Misho", character_name="Aria", estimate_tokens=_EST, flush_all=True,
    )
    assert len(forced) == 1 and forced[0].trigger == "idle" and forced[0].watermark_id == "u1"


def test_count_splits_into_contiguous_non_overlapping_windows() -> None:
    wins = _plan(_exchanges(4), n=2)
    assert [w.watermark_id for w in wins] == ["u2", "u4"]
    # No external_id appears in two windows (no re-ingestion within one plan).
    assert wins[0].episode_uuid != wins[1].episode_uuid


def test_session_gap_flushes_prior_batch() -> None:
    # Two exchanges close together, then a big time gap, then another exchange.
    turns = _exchanges(2, start_min=0) + _exchanges(1, start_min=30)  # 30-min gap > 20
    turns[-2] = WinTurn("u9", "user", "hi", "2026-07-01T09:30:00+00:00")
    turns[-1] = WinTurn("a9", "agent", "hi", "2026-07-01T09:30:00+00:00")
    wins = _plan(turns, n=5, gap=20)  # N high so only the gap can trigger
    assert len(wins) == 1
    assert wins[0].trigger == "session_gap"
    assert wins[0].watermark_id == "u2"  # the pre-gap session flushed; post-gap exchange pending


def test_size_trigger_sheds_turns() -> None:
    # One exchange (~130 chars) fits under chunk=200; two don't → each flushes on size. Three
    # exchanges → u1 and u2 flush (size), u3 left pending.
    turns = _exchanges(3, text="x" * 40)
    wins = _plan(turns, n=10, chunk=200)  # N high; size is the only trigger
    assert [w.watermark_id for w in wins] == ["u1", "u2"]
    assert all(w.trigger == "size" for w in wins)


def test_single_oversized_exchange_is_trimmed() -> None:
    huge = "y" * 5000
    turns = [_turn(1, "user", minute=0, text=huge), _turn(1, "agent", minute=0, text=huge)]
    wins = _plan(turns, n=2, chunk=300)
    assert len(wins) == 1 and wins[0].trimmed is True
    assert _EST(wins[0].body) < 300  # trimmed under budget → won't trip graphiti's split


def test_incomplete_trailing_exchange_not_flushed() -> None:
    # u3 has no reply yet → that exchange is incomplete and must not be ingested.
    turns = _exchanges(2) + [_turn(3, "user", minute=5)]
    wins = _plan(turns, n=1)  # N=1 flushes each complete exchange
    assert [w.watermark_id for w in wins] == ["u1", "u2"]  # u3 excluded


def test_leading_agent_turn_is_ignored() -> None:
    # A leading agent turn (the prior window's already-ingested reply) must not start a window
    # nor leak into the body.
    turns = [
        WinTurn("a0", "agent", "PRIOR_REPLY", "2026-07-01T09:00:00+00:00")
    ] + _exchanges(1, start_min=1)
    wins = _plan(turns, n=1)
    assert len(wins) == 1 and wins[0].watermark_id == "u1"
    assert "PRIOR_REPLY" not in wins[0].body


def test_n_change_safety_and_no_reingest_across_advance() -> None:
    turns = _exchanges(4)
    # Plan with N=2 → flush first window, "advance" watermark, re-plan the remainder.
    first = _plan(turns, n=2)[0]
    assert first.watermark_id == "u2"
    remaining = [t for t in turns if t.external_id not in {"u1", "a1", "u2", "a2"}]
    second = _plan(remaining, n=3)  # N changed mid-stream → still correct, no overlap
    # The second pass covers only the un-ingested tail; nothing from the first window recurs.
    assert all(w.episode_uuid not in {"u1", "u2"} for w in second)
    # With only 2 remaining exchanges and N=3, nothing flushes yet (stays pending).
    assert second == []
