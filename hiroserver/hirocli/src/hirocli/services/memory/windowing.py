"""Windowed batch ingestion planner (pure — no I/O).

docs/memory-eval-vs-chat-parity.md → "Ingestion — implementation design". Chat accumulates whole
exchanges (a user turn + the agent's reply) and ingests them as ONE two-speaker, timestamped
episode instead of one user turn per episode, so the extractor sees both sides as coreference
context (facts are still attributed to the user only — that clause rides on the ingest call, not
here).

This module is the correctness heart and is deliberately **pure**: given the pending turns after
the watermark plus the batching prefs, it returns the windows to flush and where the watermark
should advance. All the invariants the design promised — no re-ingestion, N-change safety, the
three flush triggers (count / session-gap / size), and the turn-granular chunk guard — are decided
here and unit-tested without touching data.db or Graphiti.

Grouping rule: turns are grouped into **exchanges** (a user turn followed by the agent turn(s)
until the next user turn). A *leading* agent turn (the prior window's already-ingested reply, which
reappears after a user-keyed watermark) is ignored by construction. The watermark advances to the
**last user message** of each flushed window, so the compound ``(created_at, external_id)`` cursor
excludes both that user turn and its reply on the next read — no turn is ever ingested twice.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field

from hiro_commons.log import Logger

log = Logger.get("SVC.MEMORY.WINDOWING")


@dataclass(frozen=True)
class WinTurn:
    """One durable (or spliced-current) conversation turn the planner windows over."""

    external_id: str
    role: str  # "user" | "agent"
    text: str
    created_at: str  # ISO-8601


@dataclass(frozen=True)
class PlannedWindow:
    """One episode to ingest: the rendered transcript plus the identity/temporal anchors."""

    body: str
    episode_uuid: str  # == the window's LAST user message external_id (provenance anchor)
    reference_time: str  # the window's LAST turn created_at (monotonic cross-window supersession)
    watermark_id: str  # advance the cursor to this (the last USER message) after ingest
    watermark_at: str
    exchange_count: int
    trigger: str  # "count" | "session_gap" | "size" — which flush trigger closed the window
    trimmed: bool = False  # a lone oversized exchange had its text trimmed to fit the budget


@dataclass
class _Exchange:
    turns: list[WinTurn] = field(default_factory=list)

    @property
    def user_turn(self) -> WinTurn:
        return self.turns[0]

    @property
    def complete(self) -> bool:
        # A user turn with at least one following agent turn. A trailing user with no reply yet is
        # incomplete → it stays pending (the reply lands next turn), never half-ingested.
        return len(self.turns) >= 2 and any(t.role == "agent" for t in self.turns[1:])

    @property
    def start_at(self) -> str:
        return self.turns[0].created_at

    @property
    def end_at(self) -> str:
        return self.turns[-1].created_at


def _parse_dt(value: str) -> dt.datetime | None:
    s = (value or "").strip()
    if not s:
        return None
    try:
        parsed = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=dt.UTC)


def _gap_minutes(prev_end: str, next_start: str) -> float:
    a, b = _parse_dt(prev_end), _parse_dt(next_start)
    if a is None or b is None:
        return 0.0  # unparseable timestamps never spuriously split a session
    return max(0.0, (b - a).total_seconds() / 60.0)


def _fmt_ts(value: str) -> str:
    d = _parse_dt(value)
    return d.strftime("%Y-%m-%d %H:%M") if d is not None else ""


def _group_exchanges(turns: list[WinTurn]) -> list[_Exchange]:
    exchanges: list[_Exchange] = []
    cur: _Exchange | None = None
    for t in turns:
        if t.role == "user":
            if cur is not None:
                exchanges.append(cur)
            cur = _Exchange(turns=[t])
        else:  # agent turn — attaches to the open exchange; a LEADING agent (cur is None) is the
            # prior window's already-ingested reply and is ignored (see module docstring).
            if cur is not None:
                cur.turns.append(t)
    if cur is not None:
        exchanges.append(cur)
    return exchanges


def _render_body(exchanges: list[_Exchange], *, user_name: str, character_name: str) -> str:
    user_label = (user_name or "User").strip() or "User"
    # Disambiguate the assistant's speaker label with an "(AI)" marker so its name can't be confused
    # with a person the user knows by the same name in episode-text (BM25) search. Keep this form
    # aligned with how the retrieval agent refers to the assistant in queries
    # (domain/prompts/memory_chat_retrieval_agent.md → ## Identities).
    agent_name = (character_name or "").strip()
    agent_label = f"{agent_name} (AI)" if agent_name else "AI assistant"
    lines: list[str] = []
    for ex in exchanges:
        for t in ex.turns:
            label = user_label if t.role == "user" else agent_label
            stamp = _fmt_ts(t.created_at)
            prefix = f"[{stamp}] " if stamp else ""
            lines.append(f"{prefix}{label}: {t.text}".rstrip())
    return "\n".join(lines)


def _trim_exchange_to_budget(
    ex: _Exchange, *, chunk_min_tokens: int, user_name: str, character_name: str,
    estimate_tokens: Callable[[str], int],
) -> _Exchange:
    """A single exchange that alone exceeds the budget — the only case we truncate *text* (a window
    of >1 exchange sheds whole turns instead). Shrink every turn's text by 25% per pass until the
    rendered episode is under the budget, so one episode stays under Graphiti's chunk threshold
    (preserving episode == chunk == point_id). Estimator-driven so it holds for any token counter."""
    texts = [t.text for t in ex.turns]
    for _ in range(64):
        cand = _Exchange(
            turns=[
                WinTurn(t.external_id, t.role, txt, t.created_at)
                for t, txt in zip(ex.turns, texts)
            ]
        )
        body = _render_body([cand], user_name=user_name, character_name=character_name)
        if estimate_tokens(body) < chunk_min_tokens or not any(texts):
            log.warning(
                "⚠️ memory windowing — trimmed oversized single exchange to fit chunk budget · "
                "user_msg=%s",
                ex.user_turn.external_id,
            )
            return cand
        texts = [txt[: (len(txt) * 3) // 4] for txt in texts]  # shed 25% each pass
    return _Exchange(
        turns=[WinTurn(t.external_id, t.role, "", t.created_at) for t in ex.turns]
    )


def _build_window(
    exchanges: list[_Exchange], *, trigger: str, user_name: str, character_name: str,
    trimmed: bool = False,
) -> PlannedWindow:
    last = exchanges[-1]
    last_user = last.user_turn  # the window's last USER turn == watermark + provenance anchor
    return PlannedWindow(
        body=_render_body(exchanges, user_name=user_name, character_name=character_name),
        episode_uuid=last_user.external_id,
        reference_time=exchanges[-1].end_at,  # last turn (the reply) → monotonic across windows
        watermark_id=last_user.external_id,
        watermark_at=last_user.created_at,
        exchange_count=len(exchanges),
        trigger=trigger,
        trimmed=trimmed,
    )


def plan_windows(
    turns: list[WinTurn],
    *,
    window_turns: int,
    session_gap_minutes: int,
    chunk_min_tokens: int,
    user_name: str,
    character_name: str,
    estimate_tokens: Callable[[str], int],
    flush_all: bool = False,
) -> list[PlannedWindow]:
    """Plan the episodes to flush from ``turns`` (pending durable turns after the watermark, plus
    the spliced current reply), oldest-first.

    Flush triggers, checked as exchanges accumulate:
      * **session-gap** — the next exchange starts more than ``session_gap_minutes`` after the
        current batch's last turn → close the batch first (a session ended).
      * **size** — adding the next exchange would reach ``chunk_min_tokens`` → close now and start a
        fresh batch with it (shed turns, don't truncate). A *single* exchange over budget is trimmed.
      * **count** — the batch reaches ``window_turns`` exchanges.

    A trailing batch that is under N with no gap is **left pending** (not returned) — it waits for
    more turns or the idle sweep. Incomplete trailing exchanges (a user turn whose reply isn't in
    ``turns`` yet) are never flushed.
    """
    n = max(1, int(window_turns))
    exchanges = [ex for ex in _group_exchanges(turns) if ex.complete]
    windows: list[PlannedWindow] = []
    batch: list[_Exchange] = []

    def flush(trigger: str) -> None:
        if batch:
            windows.append(
                _build_window(batch, trigger=trigger, user_name=user_name, character_name=character_name)
            )
            batch.clear()

    for ex in exchanges:
        # 1) session-gap: close the current batch BEFORE adding this exchange (new session).
        if batch and _gap_minutes(batch[-1].end_at, ex.start_at) > session_gap_minutes:
            flush("session_gap")
        # 2) size: would adding this exchange reach the chunk budget?
        tentative = _render_body(
            batch + [ex], user_name=user_name, character_name=character_name
        )
        if estimate_tokens(tentative) >= chunk_min_tokens:
            if batch:
                flush("size")  # shed the rest to a fresh batch starting with `ex`
            # `batch` is now empty; if `ex` alone still overflows, trim its text.
            solo = _render_body([ex], user_name=user_name, character_name=character_name)
            if estimate_tokens(solo) >= chunk_min_tokens:
                trimmed_ex = _trim_exchange_to_budget(
                    ex, chunk_min_tokens=chunk_min_tokens, user_name=user_name,
                    character_name=character_name, estimate_tokens=estimate_tokens,
                )
                windows.append(
                    _build_window([trimmed_ex], trigger="size", user_name=user_name,
                                  character_name=character_name, trimmed=True)
                )
                continue
        batch.append(ex)
        # 3) count cap
        if len(batch) >= n:
            flush("count")

    # Normally a leftover complete-but-under-N batch stays PENDING (the batching behavior). The idle
    # sweep passes flush_all=True to force the trailing partial window out (an abandoned session).
    if flush_all:
        flush("idle")
    return windows


__all__ = ["PlannedWindow", "WinTurn", "plan_windows"]
