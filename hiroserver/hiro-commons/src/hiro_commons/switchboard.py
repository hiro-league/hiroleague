"""The switchboard: what this place may reach of each outside system (hiro-docs standards/workflow.md, "Data and real
systems"). One file per test environment says each system's mode; the core and the backend kit read it here, the same
way, once at start (a change restarts the servers: hiro-work writes the file and does that).

    real   the real system, as live
    read   reads the real system; every write is refused
    fake   a stand-in answers, at no cost: the core's for AI and voices (canned answers, a soft tone); WhatsApp and
           Talker are logged, not sent. A caller with no stand-in is refused as off
    off    not reached

Where the file is: the environment variable HIRO_SWITCHBOARD (a path), set by hiro-work for env1 to env5. Not set
(live, env0): every system is real, and nothing here changes anything. Set but unreadable: every system is off, so a
broken file never opens a real system.

    from hiro_commons import switchboard
    switchboard.check("ha", write=True)      # raises Refused unless Home Assistant is real
    switchboard.mode("ai")                    # "real" | "read" | "fake" | "off"

The same file says the environment's sign-in, for interactive use (`sign_in`): "on" (as live: people sign in), "off"
(no sign-in screen: everyone is the owner) or "as" a person of the family list (no sign-in screen: everyone is that
person, with their role). The core and the backend kit read it; live and env0 name no file, so sign-in is theirs.

    switchboard.sign_in()                     # SignIn(mode="as", person="<id>", name="Mark")
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

ENV = "HIRO_SWITCHBOARD"
REAL, READ, FAKE, OFF = "real", "read", "fake", "off"
MODES = (REAL, READ, FAKE, OFF)
# Each system, what people call it, and the modes it can take (a system with nothing to write has no read; one that
# only listens has no real)
SYSTEMS: dict[str, tuple[str, tuple[str, ...]]] = {
    "ha": ("Home Assistant", (REAL, READ, OFF)),  # no fake: nothing stands in for the house yet
    "frigate": ("Frigate", (REAL, READ, OFF)),
    "mqtt": ("MQTT", (READ, OFF)),
    "ai": ("AI", (REAL, FAKE, OFF)),
    "voices": ("Voices", (REAL, FAKE, OFF)),
    "whatsapp": ("WhatsApp and notify", (REAL, FAKE, OFF)),
    "talker": ("Talker", (REAL, FAKE, OFF)),
    "adguard": ("AdGuard", (REAL, READ, OFF)),
    "dhcp": ("DHCP", (REAL, OFF)),
    "tv": ("TVs", (REAL, READ, OFF)),  # the LAN's Chromecasts: read finds them; Cast and Stop are writes
}


ON, AS = "on", "as"  # sign-in's modes, with OFF


@dataclass(frozen=True)
class SignIn:
    """A test environment's sign-in: "on", "off" (everyone is the owner) or "as" one person of the family list."""

    mode: str = ON
    person: str = ""  # "as": the core person's id
    name: str = ""  # "as": their name, for the banner

    @property
    def quick(self) -> bool:
        """No sign-in screen here."""
        return self.mode in (OFF, AS)


def sign_in_of(raw: object) -> SignIn:
    """The file's `sign_in` as a SignIn; anything unreadable, or "as" with nobody named, is on (never looser)."""
    if not isinstance(raw, dict):
        return SignIn()
    mode, person = str(raw.get("mode") or ON), str(raw.get("person") or "")
    if mode == OFF:
        return SignIn(OFF)
    if mode == AS and person:
        return SignIn(AS, person, str(raw.get("name") or ""))
    return SignIn()


class Refused(Exception):
    """A system this place may not reach that way. The message is for people: it names the system, its mode and the
    place."""

    def __init__(self, system: str, mode: str, place: str, write: bool) -> None:
        self.system, self.mode, self.place, self.write = system, mode, place, write
        name = SYSTEMS.get(system, (system,))[0]
        if mode == READ:
            what = f"{name} is read only in {place}: nothing is written there"
        elif mode == FAKE:
            what = f"{name} is fake in {place}, and this has no stand-in yet"
        else:
            what = f"{name} is off in {place}"
        super().__init__(f"{what} (its switchboard: hiro-work switch)")


@dataclass(frozen=True)
class Switchboard:
    live: bool  # no file was asked for: live or env0, everything real
    place: str = "this place"
    preset: str = ""
    modes: dict[str, str] = field(default_factory=dict)
    problem: str = ""  # the file couldn't be read: everything is off
    sign_in: SignIn = field(default_factory=SignIn)  # live and env0: never read (their own sign-in decides)

    def mode(self, system: str) -> str:
        if self.live:
            return REAL
        mode = self.modes.get(system, OFF)
        return mode if mode in SYSTEMS.get(system, ("", MODES))[1] else OFF

    def check(self, system: str, *, write: bool = False, fakes: bool = False) -> str:
        """The system's mode when this call may go on: real; read for a read; fake when the caller has a stand-in
        (`fakes`). Else Refused."""
        mode = self.mode(system)
        if mode == REAL or (mode == READ and not write) or (mode == FAKE and fakes):
            return mode
        raise Refused(system, mode, self.place, write)

    def summary(self) -> dict | None:
        """For a status route and the page's banner: None in live and env0."""
        if self.live:
            return None
        return {"place": self.place, "preset": self.preset, "problem": self.problem,
                "modes": {s: self.mode(s) for s in SYSTEMS}}

    def page(self, systems: Iterable[str]) -> dict | None:
        """For the banner on every page of a test environment: the place, its preset, and the mode of each system the
        asker names (the ones its app reaches), in the switchboard's order. None in live and env0: no banner."""
        if self.live:
            return None
        named = set(systems)
        return {"place": self.place, "preset": self.preset, "problem": self.problem,
                "sign_in": self.sign_in.mode, "sign_in_as": self.sign_in.name,
                "systems": [{"id": s, "name": name, "mode": self.mode(s)} for s, (name, _) in SYSTEMS.items()
                            if s in named]}


def read(environ: dict[str, str] | None = None) -> Switchboard:
    """The switchboard the environment names (HIRO_SWITCHBOARD); everything real when it names none."""
    path = (environ if environ is not None else os.environ).get(ENV, "").strip()
    if not path:
        return Switchboard(live=True)
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        modes = {str(k): str(v) for k, v in dict(doc["modes"]).items()}
        return Switchboard(False, str(doc.get("place") or "this environment"), str(doc.get("preset") or ""), modes,
                           sign_in=sign_in_of(doc.get("sign_in")))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return Switchboard(False, "this environment", problem=f"{path} can't be read ({type(exc).__name__}): "
                                                               "every outside system is off")


_board: Switchboard | None = None


def board() -> Switchboard:
    """This process's switchboard, read once."""
    global _board
    if _board is None:
        _board = read()
    return _board


def mode(system: str) -> str:
    return board().mode(system)


def check(system: str, *, write: bool = False, fakes: bool = False) -> str:
    return board().check(system, write=write, fakes=fakes)


def summary() -> dict | None:
    return board().summary()


def page(systems: Iterable[str]) -> dict | None:
    return board().page(systems)


def sign_in() -> SignIn:
    """This place's sign-in: on in live and env0 (no file), else what the environment's file says."""
    return board().sign_in
