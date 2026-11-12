"""What the HiroLeague core says about its AI (Phase 7a): its AI profiles, and which one each of the app's uses asks
with (the core's `ai.profiles`). The app's pickers list these and
Settings → AI from HiroLeague shows them.

The list is read through the link (hiroleague.link) when it connects, every 10 minutes while connected (the `core-ai`
worker), and when a page asks for it and the last read is older than FRESH. It is kept in memory and in the database
(setting CACHE_KEY, with when it was read), so while the core is down, or after a restart without it, the pickers
still list the last profiles it sent, with when that was. A read that fails keeps the last list and says why.

The core's answer is read loosely (`parse`, pure): a field it leaves out is left empty here, never a failure, so the
two sides can grow apart a little without breaking the pickers.
"""

import asyncio
import json
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from hiro_channel_sdk import ExtensionRequestError
from pydantic import BaseModel
from sqlmodel import Session

from .. import identity
from .. import settings
from .. import calls
from ..db import engine, run_db
from ..errors import Invalid, Unavailable, failed
from ..events import bus
from hiro_channel_sdk.workers import Worker
from ..hiroleague import CONNECTED, link
from ..extension import ext

log = identity.logger("llm")

AI_PROFILES = "ai.profiles"  # the core's request (extensions only)
AI_USES_SET = "ai.uses.set"  # Phase 7b: pick a use's profile, saved in the core
CACHE_KEY = "core_ai_profiles"  # the last list read, as JSON {"answer", "fetched_at"} (settings table)
FRESH = timedelta(seconds=30)  # a page's read asks the core again when the last read is older
EVERY = 600.0  # seconds between the worker's reads while connected
TIMEOUT = 10.0  # seconds the core may take to answer
IMPORTED = "hh-"  # the core's import (`hiro ai import-homehiro`) kept HomeHiro's old profile ids as hh-<id>

Kind = Literal["api", "local", "plan"]
Need = Literal["pictures", "sound", "json"]


def _no_core() -> str:
    return f"{identity.app().title} isn't connected to HiroLeague (Settings → HiroLeague)"


class CoreAiProfile(BaseModel):
    """One of the core's AI profiles, as the app's pickers show it."""

    id: str
    name: str
    kind: Kind  # api: paid per question; local: a server in the house; plan: a tool signed in with a plan
    provider: str  # as people read it: "Google", "Codex", "PC LM Studio"
    model: str  # as people read it
    model_id: str  # the core's `provider:model`
    sent_to: str  # where a question (and its pictures) goes
    budget: str | None = None  # the core's own words for its limit, when it sends them
    max_cost_day: float | None = None  # API: USD a day (the home's day)
    max_per_hour: int | None = None  # plan and local: asks an hour
    at_once: int = 1
    fallback_id: str | None = None
    chain: list[str] = []  # the profile, then its fallbacks, as the core walks them
    spent_today: float | None = None  # USD
    asks_today: int | None = None
    this_hour: int | None = None  # asks in this clock hour


class CoreAiUse(BaseModel):
    """One of the app's uses (the app's Extension.uses), and the core's profile it asks with now."""

    id: str  # ask, wakeword, sites, write, study
    name: str
    needs: list[Need]
    pictures_up_to: int | None = None  # when one ask carries more than one picture
    profile_id: str | None = None  # None: the core has no profile for it yet
    chain: list[str] = []  # what it tries, in order (the profile's chain)


class CoreAi(BaseModel):
    """What the app knows of the core's AI. `reachable` False: the last list read (`fetched_at`), and why it's old."""

    reachable: bool
    fetched_at: datetime | None  # when the list was read; None: never
    error: str | None = None  # why it couldn't be read now
    core: str | None = None  # the core's name and version, while connected
    profiles: list[CoreAiProfile]
    uses: list[CoreAiUse]


# --- reading the core's answer (pure) ---


def _text(d: dict, *keys: str) -> str:
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _number(d: dict, *keys: str) -> float | None:
    for k in keys:
        v = d.get(k)
        if isinstance(v, int | float) and not isinstance(v, bool):
            return float(v)
    return None


def _whole(d: dict, *keys: str) -> int | None:
    v = _number(d, *keys)
    return None if v is None else int(v)


def _kind(raw: Any) -> Kind:
    return raw if raw in ("api", "local", "plan") else "api"


def _sent_to(kind: Kind, provider: str) -> str:
    return f"{provider}, in the house" if kind == "local" else provider


def _profile(d: dict) -> CoreAiProfile | None:
    pid = _text(d, "id", "profile_id")
    if not pid:
        return None
    model_id = _text(d, "model", "model_id")
    provider = _text(d, "provider_label", "provider_name", "provider") or model_id.split(":", 1)[0]
    kind = _kind(d.get("kind"))
    today = d.get("today") if isinstance(d.get("today"), dict) else {}
    fallback = _text(d, "fallback", "fallback_id") or None
    # The core sends `fallback_chain` (the fallbacks only, in order); the chain here starts with the profile itself.
    after = d.get("fallback_chain") or d.get("chain") or []
    chain = [pid, *[str(x) for x in after if isinstance(x, str) and x != pid]]
    if len(chain) == 1 and fallback:
        chain.append(fallback)
    # The core sends its limits as a `budget` object and their words as `budget_hint`.
    raw_budget = d.get("budget")
    limits = raw_budget if isinstance(raw_budget, dict) else d
    hint = _text(d, "budget_hint") or (raw_budget if isinstance(raw_budget, str) else "")
    return CoreAiProfile(
        id=pid, name=_text(d, "label", "name") or pid, kind=kind, provider=provider,
        model=_text(d, "model_label", "model_name") or model_id.split(":", 1)[-1], model_id=model_id,
        sent_to=_text(d, "sent_to") or _sent_to(kind, provider),
        budget=hint.strip() or None,
        max_cost_day=_number(limits, "max_cost_day"), max_per_hour=_whole(limits, "max_per_hour"),
        at_once=_whole(limits, "at_once") or 1, fallback_id=fallback, chain=chain,
        spent_today=_number(today, "cost", "spent") if today else _number(d, "spent_today", "cost_today"),
        asks_today=_whole(today, "asks") if today else _whole(d, "asks_today"),
        this_hour=_whole(today, "this_hour", "hour") if today else _whole(d, "this_hour"))


def _use_map(raw: Any) -> dict[str, str | None]:
    """The core's use → profile map: {"home:ask": id} or {"ask": id}, or a list of {use, profile_id}."""
    pairs: list[tuple[Any, Any]] = []
    if isinstance(raw, dict):
        pairs = list(raw.items())
    elif isinstance(raw, list):
        pairs = [(x.get("use") or x.get("id"), x.get("profile_id") or x.get("profile")) for x in raw if isinstance(x, dict)]
    out: dict[str, str | None] = {}
    for key, pid in pairs:
        if isinstance(key, str):
            out[key.split(":", 1)[-1]] = pid if isinstance(pid, str) and pid else None
    return out


def parse(answer: Any) -> tuple[list[CoreAiProfile], dict[str, str | None]]:
    """The core's `ai.profiles` answer: its profiles (those without an id left out) and the use → profile map."""
    if not isinstance(answer, dict):
        return [], {}
    raw = answer.get("profiles")
    rows = raw.values() if isinstance(raw, dict) else raw if isinstance(raw, list) else []
    profiles = [p for d in rows if isinstance(d, dict) and (p := _profile(d))]
    return profiles, _use_map(answer.get("uses"))


def uses_of(profiles: list[CoreAiProfile], uses: dict[str, str | None]) -> list[CoreAiUse]:
    """the app's declared uses (the app's Extension.uses), each with the core's profile and what it tries."""
    by_id = {p.id: p for p in profiles}
    out = []
    for u in ext().uses:
        needs: list[Need] = [*(["pictures"] if u.pictures else []), *(["sound"] if u.sound else []),
                             *(["json"] if u.json_answer else [])]
        pid = uses.get(u.id)
        out.append(CoreAiUse(id=u.id, name=u.name, needs=needs, pictures_up_to=u.pictures if u.pictures > 1 else None,
                             profile_id=pid, chain=by_id[pid].chain if pid in by_id else ([pid] if pid else [])))
    return out


# --- the cache ---


@dataclass
class Known:
    answer: dict[str, Any] = field(default_factory=dict)  # the core's last answer, as it came
    fetched_at: datetime | None = None
    error: str | None = None
    loaded: bool = False  # read back from the database once


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
        log.warning("AI from HiroLeague: the kept list of profiles can't be read (%s); it is read again", exc)
        _known.answer, _known.fetched_at = {}, None


def _keep(session: Session, answer: dict[str, Any], at: datetime) -> None:
    settings.put(session, CACHE_KEY, json.dumps({"answer": answer, "fetched_at": at.isoformat()}))
    session.commit()


async def refresh() -> None:
    """Ask the core for its profiles now; on a failure keep the last list and say why (`Known.error`)."""
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
            answer = await client.request(AI_PROFILES, {}, timeout=TIMEOUT)
        except ExtensionRequestError as exc:
            _known.error = f"HiroLeague didn't send its AI profiles ({exc.code}): {exc.message}"
            log.warning("AI from HiroLeague: %s", _known.error)
            return
        calls.done(log, f"HiroLeague: {AI_PROFILES}", started, timeout=TIMEOUT)
        at = datetime.now(UTC)
        _known.answer, _known.fetched_at, _known.error = answer if isinstance(answer, dict) else {}, at, None
        try:
            await run_db(_keep, _known.answer, at)
        except Exception as exc:  # the list read counts more than its copy (backend guide, section 5.7)
            failed(log, "AI from HiroLeague: keeping the list of profiles", exc)


async def read() -> CoreAi:
    """What the pickers and Settings show: read again when older than FRESH, else the last list."""
    await run_db(_load)
    if not link.client.connected:
        _known.error = _no_core()  # the last list, as it was
    elif not _known.fetched_at or datetime.now(UTC) - _known.fetched_at > FRESH or _known.error:
        await refresh()
    profiles, uses = parse(_known.answer)
    status = link.status()
    core = status.get("core") or {}
    return CoreAi(reachable=_known.error is None and link.client.connected, fetched_at=_known.fetched_at,
                  error=_known.error, core=f"{core.get('name') or 'HiroLeague'} {core.get('version') or ''}".strip() if core else None,
                  profiles=profiles, uses=uses_of(profiles, uses))


async def set_use(use: str, profile_id: str | None) -> None:
    """Phase 7b: pick the profile one of the app's uses asks with, saved in the core's ai.uses (`ai.uses.set`);
    the list is read again so the page shows it."""
    if not link.client.connected:
        raise Unavailable(_no_core())
    try:
        await link.client.request(AI_USES_SET, {"use": use, "profile": profile_id}, timeout=TIMEOUT)
    except ExtensionRequestError as exc:
        raise Invalid(f"Not saved in HiroLeague: {exc.message}") from exc
    await refresh()


def _profile_ids() -> set[str] | None:
    """The ids the core listed last; None when it never sent a list (nothing to check against)."""
    if not _known.loaded:
        with Session(engine) as session:
            _load(session)
    if _known.fetched_at is None:
        return None
    return {p.id for p in parse(_known.answer)[0]}


def resolve(profile_id: str) -> str:
    """The core's id for a profile a copy saved: as it is, or as the core's import renamed HomeHiro's own (hh-<id>)."""
    ids = _profile_ids()
    if ids is None or profile_id in ids or f"{IMPORTED}{profile_id}" not in ids:
        return profile_id
    return f"{IMPORTED}{profile_id}"


async def resolved(profile_id: str) -> str:
    """`resolve`, from the event loop: the kept list is read from the database in a thread first."""
    await run_db(_load)
    return resolve(profile_id)


def exists(profile_id: str) -> bool:
    """For settings checks (a copy's profile still there?): True while no list is known (the core decides then)."""
    ids = _profile_ids()
    return ids is None or resolve(profile_id) in ids


def name_of(profile_id: str | None) -> str | None:
    """A profile's name as the core last listed it."""
    if not profile_id:
        return None
    return next((p.name for p in parse(_known.answer)[0] if p.id == profile_id), None)


class CoreAiReader(Worker):
    """Reads the core's profiles when the link connects and every EVERY seconds while connected."""

    name = "core-ai"

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
                continue  # keeps the last list; the next connect reads again
            try:
                await refresh()
            except Exception as exc:  # one bad round never ends the loop; logged, the next round tries again
                failed(log, "AI from HiroLeague: reading the core's profiles", exc)


reader = CoreAiReader()
