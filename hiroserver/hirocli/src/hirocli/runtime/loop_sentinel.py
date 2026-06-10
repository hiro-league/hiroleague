"""Event-loop stall sentinel — turns silent process freezes into named log evidence.

Why this exists
---------------
A native call that holds the GIL (observed: Kuzu's CHECKPOINT wait inside
``CREATE_FTS_INDEX``, ~2.5 minutes) starves the entire asyncio event loop: no request is
served, no log line is written, websocket handshakes pile up — and the server logs NOTHING
during the stall, so the incident is invisible afterward except by inference. This sentinel
sleeps on a fixed interval and measures the drift between the expected and actual wake-up;
a large drift means the loop (or the whole interpreter) was stalled for that long. One
WARNING line per stall, written the moment the loop recovers.

It cannot *prevent* a stall (nothing running on the starved loop can) — it exists so the
next one is a labeled, measurable log line instead of a silent gap. Pair with the snapshot
read open/close logs (graphiti_service) to identify which reader was in flight.
"""

from __future__ import annotations

import asyncio
import time

from hiro_commons.log import Logger

log = Logger.get("RUNTIME.LOOP")

# How often the sentinel wakes (seconds). Cheap: one no-op task wake per interval.
_INTERVAL_S = 5.0
# Drift beyond which the wake-up is considered a stall worth reporting. Scheduling jitter
# on a busy-but-healthy loop is milliseconds; ≥2s of drift means something held the loop.
_WARN_DRIFT_S = 2.0


async def run_loop_stall_sentinel(
    interval_s: float = _INTERVAL_S, warn_drift_s: float = _WARN_DRIFT_S
) -> None:
    """Run forever, logging a WARNING whenever the event loop stalls beyond the threshold.

    Launched as one of the server's long-lived coroutines (server_process); cancelled with
    the rest of them on shutdown."""
    log.info("✅ loop-stall sentinel started · interval=%.0fs · threshold=%.1fs", interval_s, warn_drift_s)
    while True:
        before = time.monotonic()
        await asyncio.sleep(interval_s)
        drift = time.monotonic() - before - interval_s
        if drift >= warn_drift_s:
            log.warning(
                "⚠️ event loop stalled ~%.1fs — a blocking/native call starved the server "
                "(check for an open graph read just before this line)",
                drift,
            )
