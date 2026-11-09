"""Every paid AI call the core makes, per clock hour — workspace.db ``ai_calls`` (Phase 7b).

One row is one UTC hour × one combination of: kind (a question, speech, transcription, an image,
embeddings), source (``hiro`` for the core's own jobs, else the extension's name), use (the job or
the extension's use id), AI profile, provider, model, who pays (``api`` key, ``plan``, ``local``
server), the person it was for (a person id, Phase 6), a free label the asker sent, and the result
(``ok``, ``fell back`` to another profile, ``failed``). Each row sums requests, tokens, time, the
billed cost (API keys), the estimate (what a plan's calls would cost on an API key) and how many
answered calls went without a price (``unpriced``: counted at $0), as HomeHiro's usage page showed.

Rows are kept for good (the AI usage page reads any range); a profile's limits read today's and
this hour's rows (``profile_usage``). Synchronous sqlite3: async callers use ``record_async``.
Counting must never break the call it counts, so ``record`` / ``record_async`` log and swallow errors.
"""

from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from hiro_commons.log import Logger

from ...domain.db import db_path, ensure_db

log = Logger.get("AI.USAGE")

HIRO_SOURCE = "hiro"
KINDS = ("question", "speech", "transcription", "image", "embedding", "rerank")
BILLINGS = ("api", "plan", "local")
RESULTS = ("ok", "fell back", "failed")

# The columns that make a row (its key) and the ones it sums.
_KEY = ("hour", "kind", "source", "use_id", "profile_id", "provider", "model", "billing", "person_id", "label", "result")
_SUMS = ("requests", "tokens_in", "tokens_out", "ms", "cost", "estimate", "unpriced")


@dataclass(frozen=True)
class UsageCall:
    """One call (or ``requests`` alike calls) to count."""

    kind: str
    source: str
    use: str = ""
    profile_id: str = ""
    profile_name: str = ""  # kept so a deleted profile still reads by its name
    provider: str = ""
    model: str = ""
    billing: str = "api"
    person_id: str = ""
    label: str = ""
    result: str = "ok"
    requests: int = 1
    tokens_in: int = 0
    tokens_out: int = 0
    ms: int = 0
    cost: float = 0.0
    estimate: float = 0.0
    unpriced: int = 0  # answered calls counted at $0 for want of a price (or of token counts)


@dataclass(frozen=True)
class ProfileUsage:
    asks_today: int
    cost_today: float
    asks_this_hour: int


def hour_start(at: datetime) -> datetime:
    return at.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def local_day_start(now: datetime) -> datetime:
    """Midnight of the server's local day containing ``now``, as a UTC moment."""
    return now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)


def hour_key(at: datetime) -> str:
    return hour_start(at).strftime("%Y-%m-%dT%H:00:00Z")


def _check(call: UsageCall) -> None:
    if call.kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    if call.billing not in BILLINGS:
        raise ValueError(f"billing must be one of {', '.join(BILLINGS)}")
    if call.result not in RESULTS:
        raise ValueError(f"result must be one of {', '.join(RESULTS)}")
    if not call.source:
        raise ValueError("source is required")


def _upsert(conn: sqlite3.Connection, hour: str, call: UsageCall) -> None:
    conn.execute(
        f"INSERT INTO ai_calls ({', '.join(_KEY)}, profile_name, {', '.join(_SUMS)}) "
        f"VALUES ({', '.join('?' * (len(_KEY) + 1 + len(_SUMS)))}) "
        f"ON CONFLICT({', '.join(_KEY)}) DO UPDATE SET "
        "profile_name = CASE WHEN excluded.profile_name != '' THEN excluded.profile_name ELSE profile_name END, "
        + ", ".join(f"{c} = {c} + excluded.{c}" for c in _SUMS),
        (
            hour,
            call.kind,
            call.source,
            call.use,
            call.profile_id,
            call.provider,
            call.model,
            call.billing,
            call.person_id,
            call.label.strip()[:80],
            call.result,
            call.profile_name,
            int(call.requests),
            int(call.tokens_in or 0),
            int(call.tokens_out or 0),
            int(call.ms or 0),
            float(call.cost or 0.0),
            float(call.estimate or 0.0),
            int(call.unpriced or 0),
        ),
    )


def record_strict(workspace_path: Path, call: UsageCall, now: datetime | None = None) -> None:
    """Count ``call`` in its hour; raises on a bad call or a DB error (tests, imports)."""
    _check(call)
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        _upsert(conn, hour_key(now or datetime.now(UTC)), call)
        conn.commit()


def record(workspace_path: Path, call: UsageCall, now: datetime | None = None) -> None:
    """Count ``call``; a failure is logged, never raised (the call itself counts more than its count)."""
    try:
        record_strict(workspace_path, call, now)
    except Exception as exc:
        log.error(f"❌ AI call not counted — {call.source} · {call.use or call.kind}", error=str(exc), exc_info=True)


async def record_async(workspace_path: Path, call: UsageCall) -> None:
    await asyncio.to_thread(record, workspace_path, call, datetime.now(UTC))


def add_rows(workspace_path: Path, rows: list[tuple[str, UsageCall]]) -> int:
    """Add already-summed rows (``(hour key, call)``) in one transaction — the one-time HomeHiro import."""
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        for hour, call in rows:
            _check(call)
            _upsert(conn, hour, call)
        conn.commit()
    return len(rows)


def profile_usage(workspace_path: Path, profile_id: str, now: datetime | None = None) -> ProfileUsage:
    """What a profile answered today (the server's local day) and this hour — what its limits read.

    Failed calls don't count: they cost nothing and a profile that keeps failing must not run out.
    Questions only: an image or voice profile's id is another kind of profile.
    """
    now = now or datetime.now(UTC)
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        today = conn.execute(
            "SELECT COALESCE(SUM(requests), 0), COALESCE(SUM(cost), 0.0) FROM ai_calls "
            "WHERE profile_id = ? AND hour >= ? AND result != 'failed' AND kind = 'question'",
            (profile_id, hour_key(local_day_start(now))),
        ).fetchone()
        hour = conn.execute(
            "SELECT COALESCE(SUM(requests), 0) FROM ai_calls WHERE profile_id = ? AND hour = ? AND result != 'failed' AND kind = 'question'",
            (profile_id, hour_key(now)),
        ).fetchone()
    return ProfileUsage(asks_today=int(today[0]), cost_today=float(today[1]), asks_this_hour=int(hour[0]))


def read_rows(workspace_path: Path, start: datetime, end: datetime) -> list[dict[str, Any]]:
    """The rows of the hours that overlap [start, end), as stored (ids, not names)."""
    end_hour = hour_start(end)
    # An end inside an hour (a half-hour time zone's midnight) still takes that hour.
    end_key = hour_key(end_hour if end_hour == end.astimezone(UTC) else end_hour + timedelta(hours=1))
    ensure_db(workspace_path)
    with sqlite3.connect(str(db_path(workspace_path))) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT * FROM ai_calls WHERE hour >= ? AND hour < ? ORDER BY hour", (hour_key(start), end_key)
        )
        return [dict(r) for r in cur.fetchall()]
