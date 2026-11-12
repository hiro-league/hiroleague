"""Voices from HiroLeague: the app speaks through the core, and lists its voice profiles for the pickers.

The core keeps the voice profiles (model, voice, speaking style, speed), Gemini's designed voices and the spoken-clip
cache, and speaks for the app (`voice.speak`): text in, an OGG/Opus clip out (HomeHiro plays it on the camera speakers,
talker.py). The app declares its voice use (`Extension.voice_uses`, HomeHiro's `speak`): the core's admin, or the
app's page, picks the profile it speaks with by default; a pick of its own (an alert, a Speak node) wins. An app with no
voice use (NetHiro) only lists the profiles: it speaks by asking HomeHiro.

The core's profiles are read through the link (`voice.profiles`) when it connects, every 10 minutes while connected
(the `core-voices` worker) and when a page asks and the last read is older than FRESH; the last list is kept in
memory and in the database (setting CACHE_KEY), so the pickers still list it while the core is down. Profiles are
edited only in the core's admin.

Old picks keep working: the core's import (`hiro voice import-homehiro`) kept HomeHiro's TTS profile ids as `hh-<id>`,
and `resolve` asks with that id when the core has it.

Backend kit, step 5: HomeHiro's and NetHiro's copies; HomeHiro's had all of it, NetHiro's the list.
"""

import asyncio
import base64
import binascii
import json
import logging
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from hiro_channel_sdk import ExtensionRequestError
from hiro_channel_sdk.constants import METHOD_VOICE_PROFILES, METHOD_VOICE_SPEAK, METHOD_VOICE_USES_SET
from pydantic import BaseModel
from sqlmodel import Session

from . import identity, settings
from . import calls
from .db import engine, run_db
from .errors import Invalid, OutsideError, Unavailable, failed
from .events import bus
from hiro_channel_sdk.workers import Worker
from .extension import ext
from .hiroleague import CONNECTED, link

log = identity.logger("voices")

CACHE_KEY = "core_voice_profiles"  # the last list read, as JSON {"answer", "fetched_at"} (settings table)
FRESH = timedelta(seconds=30)
EVERY = 600.0
TIMEOUT = 10.0  # reading the list
SPEAK_TIMEOUT = 120.0  # a clip the core has to make (a long text on Gemini takes a while)
IMPORTED = "hh-"  # the core's import kept HomeHiro's TTS profile ids as hh-<id>


def _no_core() -> str:
    return f"{identity.app().title} isn't connected to HiroLeague (Settings → HiroLeague)"


def _voice_use() -> str | None:
    """The app's voice use (its first `Extension.voice_uses`, HomeHiro's `speak`); None: it speaks with none."""
    uses = ext().voice_uses
    return uses[0].id if uses else None


class VoiceError(OutsideError):
    """The core couldn't speak (the provider failed, or no answer in time)."""


class CoreVoice(BaseModel):
    """One of the core's voice profiles, as the app's pickers show it."""

    id: str
    name: str
    line: str = ""  # "Google · gemini-3.8-flash-tts · Kore"


class CoreVoices(BaseModel):
    """What the app knows of the core's voices. `reachable` False: the last list (`fetched_at`), and why it's old."""

    reachable: bool
    fetched_at: datetime | None
    error: str | None = None
    profiles: list[CoreVoice]
    default_id: str | None = None  # the profile the app's voice use speaks with in the core; None: none picked


@dataclass
class Spoken:
    ogg: bytes
    seconds: float
    waveform: bytes
    cost: float | None  # USD; 0 from the core's clip cache; None: no price
    cached: bool
    profile_name: str


# --- reading the core's answer (pure) ---


def parse(answer: Any) -> tuple[list[CoreVoice], str | None]:
    """The core's `voice.profiles` answer: its profiles (those without an id left out) and the Speak use's pick."""
    if not isinstance(answer, dict):
        return [], None
    rows = answer.get("profiles")
    if not isinstance(rows, list):
        rows = []
    profiles = [
        CoreVoice(id=str(d["id"]), name=str(d.get("name") or d["id"]), line=str(d.get("line") or ""))
        for d in rows
        if isinstance(d, dict) and isinstance(d.get("id"), str) and d["id"]
    ]
    uses = answer.get("uses")
    use = _voice_use()
    pick = uses.get(use) if isinstance(uses, dict) and use else None
    return profiles, pick if isinstance(pick, str) and pick else None


# --- the cache ---


@dataclass
class Known:
    answer: dict[str, Any] = field(default_factory=dict)
    fetched_at: datetime | None = None
    error: str | None = None
    loaded: bool = False


_known = Known()
_lock: asyncio.Lock | None = None


def _load(session: Session) -> None:
    if _known.loaded:
        return
    _known.loaded = True
    raw = settings.get(session, CACHE_KEY)
    if not raw:
        return
    try:
        kept = json.loads(raw)
        _known.answer = kept["answer"] if isinstance(kept.get("answer"), dict) else {}
        _known.fetched_at = datetime.fromisoformat(kept["fetched_at"])
    except (ValueError, KeyError, TypeError, AttributeError) as exc:  # a broken copy: read again from the core
        log.warning("Voices from HiroLeague: the kept list can't be read (%s); it is read again", exc)
        _known.answer, _known.fetched_at = {}, None


def _keep(session: Session, answer: dict[str, Any], at: datetime) -> None:
    settings.put(session, CACHE_KEY, json.dumps({"answer": answer, "fetched_at": at.isoformat()}))
    session.commit()


async def refresh() -> None:
    """Ask the core for its voice profiles now; on a failure keep the last list and say why."""
    global _lock
    _lock = _lock or asyncio.Lock()
    async with _lock:
        await run_db(_load)
        client = link.client
        if not client.connected:
            _known.error = _no_core()
            return
        started = calls.start()
        try:
            answer = await client.request(METHOD_VOICE_PROFILES, {}, timeout=TIMEOUT)
        except ExtensionRequestError as exc:
            _known.error = f"HiroLeague didn't send its voice profiles ({exc.code}): {exc.message}"
            log.warning("Voices from HiroLeague: %s", _known.error)
            return
        calls.done(log, f"HiroLeague: {METHOD_VOICE_PROFILES}", started, timeout=TIMEOUT)
        at = datetime.now(UTC)
        _known.answer, _known.fetched_at, _known.error = answer if isinstance(answer, dict) else {}, at, None
        try:
            await run_db(_keep, _known.answer, at)
        except Exception as exc:  # the list read counts more than its copy
            failed(log, "Voices from HiroLeague: keeping the list of profiles", exc)


async def read() -> CoreVoices:
    """What the page and the pickers show: read again when older than FRESH, else the last list."""
    await run_db(_load)
    if not link.client.connected:
        _known.error = _no_core()
    elif not _known.fetched_at or datetime.now(UTC) - _known.fetched_at > FRESH or _known.error:
        await refresh()
    profiles, default_id = parse(_known.answer)
    return CoreVoices(reachable=_known.error is None and link.client.connected, fetched_at=_known.fetched_at,
                      error=_known.error, profiles=profiles, default_id=default_id)


def choices(session: Session) -> list[dict[str, str]]:
    """For the pickers (an alert's speaker, the Speak node): the core's profiles as it last listed them."""
    _load(session)
    return [{"id": p.id, "name": p.name} for p in parse(_known.answer)[0]]


def _ensure_loaded() -> None:
    """The kept list, read from the database once (sync callers: the Speak node's checks)."""
    if not _known.loaded:
        with Session(engine) as session:
            _load(session)


def choices_known() -> bool:
    """A list was ever read from the core (else nothing to check a pick against: the core decides)."""
    _ensure_loaded()
    return _known.fetched_at is not None


def resolve(profile_id: str) -> str:
    """The core's id for a saved pick: as it is, or as the core's import renamed HomeHiro's own (hh-<id>)."""
    ids = {p.id for p in parse(_known.answer)[0]}
    if not ids or profile_id in ids or f"{IMPORTED}{profile_id}" not in ids:
        return profile_id
    return f"{IMPORTED}{profile_id}"


def name_of(profile_id: str | None) -> str | None:
    if not profile_id:
        return None
    _ensure_loaded()
    pid = resolve(profile_id)
    return next((p.name for p in parse(_known.answer)[0] if p.id == pid), None)


# --- speaking ---


def _refused(exc: ExtensionRequestError) -> Exception:
    """The core's refusal as the error callers handle."""
    if exc.code == "not_connected":
        return Unavailable(f"Not said: {_no_core()}")
    if exc.code == "no_profile":
        return Invalid(f"No voice: {exc.message}")
    if exc.code == "invalid":
        return Invalid(f"HiroLeague refused to say it: {exc.message}")
    if exc.code == "timeout":
        return VoiceError(f"HiroLeague didn't answer in {SPEAK_TIMEOUT:.0f} s")
    return VoiceError(f"HiroLeague couldn't say it: {exc.message}")


async def speak(profile_id: str | None, text: str, *, label: str = "") -> Spoken:
    """Say `text` with a profile of the core's (None or "": its voice use's default). Raises Unavailable without the
    core, Invalid when it refuses (no voice picked, too long), VoiceError when it failed."""
    if not link.client.connected:
        raise Unavailable(f"Not said: {_no_core()}")
    await run_db(_load)
    use = _voice_use()
    if use is None:
        raise Invalid(f"{identity.app().title} declares no voice use, so it can't speak")
    params: dict[str, Any] = {"use": use, "text": text}
    if profile_id:
        params["profile"] = resolve(profile_id)
    if label.strip():
        params["label"] = label.strip()[:80]
    started = calls.start()
    try:
        answer = await link.client.request(METHOD_VOICE_SPEAK, params, timeout=SPEAK_TIMEOUT)
    except ExtensionRequestError as exc:
        raise _refused(exc) from exc
    calls.done(log, f"HiroLeague: {METHOD_VOICE_SPEAK}", started, timeout=SPEAK_TIMEOUT, paid=True)
    try:
        ogg = base64.b64decode(answer["ogg_b64"], validate=True)
        wave = base64.b64decode(answer.get("waveform_b64") or "", validate=True)
        cost = answer.get("cost")
        return Spoken(ogg, float(answer["seconds"]), wave, float(cost) if isinstance(cost, int | float) else None,
                      bool(answer.get("cached")), str(answer.get("profile_name") or ""))
    except (KeyError, TypeError, ValueError, binascii.Error) as exc:
        raise VoiceError(f"HiroLeague's clip can't be read ({type(exc).__name__})") from exc


async def set_default(profile_id: str | None) -> None:
    """Pick the profile the app's voice use speaks with (saved in the core's voice.uses)."""
    if not link.client.connected:
        raise Unavailable(_no_core())
    try:
        await link.client.request(METHOD_VOICE_USES_SET, {"use": _voice_use(), "profile": profile_id}, timeout=TIMEOUT)
    except ExtensionRequestError as exc:
        raise Invalid(f"Not saved in HiroLeague: {exc.message}") from exc
    await refresh()


class CoreVoicesReader(Worker):
    """Reads the core's voice profiles when the link connects and every EVERY seconds while connected."""

    name = "core-voices"

    def __init__(self) -> None:
        super().__init__()
        self._due: asyncio.Event | None = None
        self._unsubscribe = None

    def on_start(self) -> None:
        self._due = asyncio.Event()
        self._unsubscribe = bus.subscribe(CONNECTED, self._now)
        self.spawn(self._loop(), "read")

    def on_stop(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None

    def _now(self, _kind: str, _data: Any) -> None:
        if self._due is not None:
            self._due.set()

    async def _loop(self) -> None:
        assert self._due is not None
        while True:
            with suppress(TimeoutError):
                await asyncio.wait_for(self._due.wait(), EVERY)
            self._due.clear()
            if not self.running:
                return
            if not link.client.connected:
                continue
            try:
                await refresh()
            except Exception as exc:  # one bad round never ends the loop
                failed(log, "Voices from HiroLeague: reading the core's profiles", exc)


reader = CoreVoicesReader()
