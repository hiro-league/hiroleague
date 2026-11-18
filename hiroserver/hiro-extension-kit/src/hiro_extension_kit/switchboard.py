"""The switchboard's gate for an app's own outside systems (Home Assistant, Frigate, MQTT, Talker, AdGuard, DHCP).

A test environment's switchboard says what it may reach of each outside system (hiro_commons.switchboard; hiro-docs
standards/workflow.md, "Data and real systems"). The systems an app reaches through the core (AI, voices, WhatsApp) are
checked there, once for every app. The ones an app reaches itself are checked here: each outside client calls `gate`
before a call, so the rule is in one place per client and a page can't forget it.

    from hiro_extension_kit import switchboard

    switchboard.gate("ha")               # before a read
    switchboard.gate("ha", write=True)   # before an action: refused when Home Assistant is read only, fake or off

In live and env0 no switchboard is named, everything is real, and `gate` does nothing. A refused call raises
`Unavailable` (503) with words for the person: the system, its mode and the place. A client that starts a connection
of its own (HA's websocket, MQTT) asks `reaches(system)` first and doesn't start when it is False.
"""

from __future__ import annotations

from hiro_commons import switchboard as _board

from .errors import Unavailable

REAL, READ, FAKE, OFF = _board.REAL, _board.READ, _board.FAKE, _board.OFF


def mode(system: str) -> str:
    """The system's mode here: real, read, fake or off."""
    return _board.mode(system)


def gate(system: str, *, write: bool = False, fakes: bool = False) -> str:
    """Go on (returning the mode) or raise Unavailable: a write needs real; a read needs real or read; `fakes` says
    the caller has a stand-in and takes the fake mode itself."""
    try:
        return _board.check(system, write=write, fakes=fakes)
    except _board.Refused as exc:
        raise Unavailable(str(exc)) from exc


def reaches(system: str) -> bool:
    """Whether the real system is reached at all here (real or read only): for a client deciding whether to connect."""
    return _board.mode(system) in (REAL, READ)


def writes(system: str) -> bool:
    """Whether the real system may be written to here."""
    return _board.mode(system) == REAL


def summary() -> dict | None:
    """The place, its preset and each system's mode, for a status route; None in live and env0."""
    return _board.summary()
