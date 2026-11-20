"""How long calls to outside systems (HA, Frigate, the HiroLeague core, the paid APIs) take, written to the log.

Each wrapper that talks to an outside system times its calls here, so the timings come from one place:
- a call that used half its time limit or more (at least 2 s) is a warning: it is close to failing;
- a paid call (TTS, LLMs) is always logged at INFO: they are few, and each one costs money;
- every other call is logged at DEBUG only.
A failed call is raised to its caller, which logs it with the reason.

Each line is a timed step of the story the call is part of (the logging plan): it carries the story's id like every
line logged inside one (a page request, a worker's round...), and its time as the field `elapsed_ms`. The call
itself sends no id out: HA, Frigate and the AI providers don't take one.
"""

import logging
import time

SLOW_FLOOR = 2.0  # seconds: never warn about a call quicker than this


def start() -> float:
    return time.perf_counter()


def elapsed(started: float) -> float:
    return time.perf_counter() - started


def slow_after(timeout: float) -> float:
    return max(SLOW_FLOOR, timeout / 2)


def done(log: logging.Logger, what: str, started: float, *, timeout: float, paid: bool = False) -> None:
    """Log a call that answered: `what` names it, e.g. "HA: config/device_registry/list"."""
    seconds = elapsed(started)
    fields = {"call": what, "elapsed_ms": round(seconds * 1000)}
    if seconds >= slow_after(timeout):
        log.warning("%s was slow: %.1f s (limit %.0f s)", what, seconds, timeout, extra=fields)
    elif paid:
        log.info("%s answered in %d ms", what, seconds * 1000, extra=fields)
    else:
        log.debug("%s answered in %d ms", what, seconds * 1000, extra=fields)

