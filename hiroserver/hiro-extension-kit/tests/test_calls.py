"""Timing calls to outside systems (calls.py): a slow call is a warning, a paid call is INFO, the rest DEBUG."""

import logging

from hiro_extension_kit import calls


def records(caplog, name: str) -> list[tuple[str, str]]:
    return [(r.levelname, r.getMessage()) for r in caplog.records if r.name == name]


def test_a_call_that_used_half_its_time_is_a_warning(caplog):
    log = logging.getLogger("testapp.test")
    with caplog.at_level(logging.DEBUG, "testapp.test"):
        calls.done(log, "HA: get_states", calls.start() - 6, timeout=10)
        calls.done(log, "HA: get_states", calls.start() - 1, timeout=10)
        calls.done(log, "Gemini: POST /x", calls.start() - 1, timeout=90, paid=True)
    (slow_level, slow), (fast_level, _), (paid_level, paid) = records(caplog, "testapp.test")
    assert slow_level == "WARNING" and slow.startswith("HA: get_states was slow: 6.0 s (limit 10 s)")
    assert fast_level == "DEBUG"
    assert paid_level == "INFO" and paid.startswith("Gemini: POST /x answered in ")


def test_short_calls_are_never_slow_whatever_their_limit():
    assert calls.slow_after(1) == calls.SLOW_FLOOR
    assert calls.slow_after(30) == 15
