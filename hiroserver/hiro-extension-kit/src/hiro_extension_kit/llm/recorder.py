"""The LLM requests log (Logs → LLM requests): every question sent to an LLM, as sent and as answered.

Whatever asks opens a request, `async with recording(source, task, link, camera)`, and may label what it sends
(`describe`: its words in parts, each with where it came from, and its pictures) and say what it did with the
answer (`outcome`). Since Phase 7a the HiroLeague core asks the models (profiles.py): from its answer profiles.py adds
a try for each model the core asked (`trying`), with who pays for it (`billing`), and a note for each profile passed
over (`passed_over`). A try holds the words and pictures as the app sent them, the schema, the reply as it came,
tokens and time. Nothing here knows a kind: labels are the asker's, and the page reads any schema and reply.

A question asked outside any `recording` is kept too, as "Other". A request with no try (every profile passed over)
isn't kept. Rows are kept KEEP_DAYS, their pictures PICTURE_DAYS (DATA_DIR/llm-requests/<id>/<n>.jpg). What the
requests add up to is counted by the HiroLeague core since Phase 7b (its Logs → AI usage). Recording never stops a
question: a failure to save is logged.
"""

import io
import shutil
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from PIL import Image
from sqlmodel import Session, col, delete, select

from .. import identity
from .. import files
from ..db import run_db
from ..errors import failed
from ..events import bus
from .models import LlmRequest

log = identity.logger("llm")

ROOT = identity.app().data_dir / "llm-requests"
KEEP_DAYS = 14
PICTURE_DAYS = 3
PRUNE_EVERY = timedelta(hours=1)
NOTICE = "llm"  # the bus notice pages reload on (an app that uses llm/ lists it in its NOTICES)
OPENAI_LOW = 512  # px: OpenAI's low detail fits every picture into 512 × 512


@dataclass
class Try:
    """One model asked."""

    provider: str  # the provider as the core named it ("google", "codex", "lm_studio")
    model: str
    prompt: str
    pictures: list[bytes]
    schema: dict
    detail: str | None
    thinking: str | None
    profile: str | None = None
    billing: str = "api"  # who pays: "api" (per question), "plan" (the owner's plan) or "local" (a home PC)
    ok: bool = False
    outcome: str = "no answer"
    reply: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    ms: int = 0
    cost: float | None = None
    estimate: float | None = None  # on a plan: what it would cost on an API key, when the tool says its cache use
    alone: "Request | None" = None  # asked outside any recording: saved by `done`

    def answered(self, text: str, tokens_in: int, tokens_out: int, ms: int, cost: float | None = None) -> None:
        self.ok, self.outcome, self.reply = True, "answered", text
        self.tokens_in, self.tokens_out, self.ms, self.cost = tokens_in, tokens_out, ms, cost

    def failed(self, exc: BaseException, ms: int = 0) -> None:
        self.ok, self.outcome, self.ms = False, str(exc) or type(exc).__name__, ms


@dataclass
class Request:
    source: str
    task: str
    link: str | None = None
    camera: str | None = None
    at: datetime = field(default_factory=lambda: datetime.now(UTC))
    parts: list[dict] | None = None  # {label, link, text}; None: the words as one part
    labels: list[str] = field(default_factory=list)  # the pictures', in the order sent
    tries: list[Try] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # profiles passed over, and why
    profile: str | None = None  # the profile being asked (set before each try)
    outcome: str | None = None
    error: str | None = None


_current: ContextVar[Request | None] = ContextVar("llm_request", default=None)
_pruned_at: datetime | None = None


@asynccontextmanager
async def recording(source: str, task: str, link: str | None = None, camera: str | None = None) -> AsyncIterator[Request]:
    """One request, kept when the block ends (with the error, if it raised)."""
    req = Request(source, task or source, link, camera)
    token = _current.set(req)
    try:
        yield req
    except BaseException as exc:
        req.error = str(exc) or type(exc).__name__
        raise
    finally:
        _current.reset(token)
        await keep(req)


def describe(parts: list[tuple[str, str | None, str]] | None = None, pictures: list[str] | None = None) -> None:
    """Label the current request's words (label, link, text; joined by blank lines they are the words) and pictures."""
    req = _current.get()
    if req is None:
        return
    if parts is not None:
        req.parts = [{"label": label, "link": link, "text": text} for label, link, text in parts if text.strip()]
    if pictures is not None:
        req.labels = list(pictures)


def active() -> bool:
    """A request is open (an asker's `recording`)."""
    return _current.get() is not None


def labels() -> list[str]:
    """The current request's picture labels, in the order sent (none: no request, or none given)."""
    req = _current.get()
    return list(req.labels) if req else []


def usage_label() -> str | None:
    """What the core's AI usage files the current request under (Phase 7b): its camera, else its task (an
    automation's or app question's name); none for a question asked without a label."""
    req = _current.get()
    if req is None or req.source == "Other":
        return None
    return (req.camera or req.task or "").strip()[:80] or None


def outcome(text: str) -> None:
    """What the app did with the answer."""
    if req := _current.get():
        req.outcome = text


def asking(profile: str) -> None:
    """The profile the next try is asked by."""
    if req := _current.get():
        req.profile = profile


def passed_over(note: str) -> None:
    if req := _current.get():
        req.notes.append(note)


def trying(provider: str, model: str, prompt: str, pictures: list[bytes], schema: dict, detail: str | None,
           thinking: str | None, billing: str = "api", profile: str | None = None) -> Try:
    """A model asked, in the current request (or one of its own, "Other", saved by `done`). `profile`: the profile it
    was asked by (else the one `asking` named)."""
    req = _current.get()
    t = Try(provider, model, prompt, [p for p in pictures if p], schema, detail, thinking, billing=billing)
    if req is None:
        req = Request("Other", "Asked without a label")
        t.alone = req
    t.profile = profile or req.profile
    req.tries.append(t)
    return t


async def done(t: Try) -> None:
    """After a try: keeps a request asked outside any recording."""
    if t.alone is not None:
        await keep(t.alone)


async def keep(req: Request) -> None:
    if not req.tries:
        return
    try:
        await run_db(_save, req)
    except Exception as exc:  # the question counts more than its log
        failed(log, f"LLM requests: keeping {req.source} {req.task!r}", exc)


# --- saving ---


def _parts(req: Request, prompt: str) -> list[dict]:
    """The asker's labelled parts, and whatever was added on the way (a profile's instructions, a tool's note);
    the words as one part when the parts aren't what was sent."""
    if not req.parts:
        return [{"label": "The words", "link": None, "text": prompt}]
    joined = "\n\n".join(p["text"] for p in req.parts)
    if not prompt.startswith(joined):
        return [{"label": "The words", "link": None, "text": prompt}]
    rest = prompt[len(joined):].strip()
    return [*req.parts, *([{"label": "Added on the way (the profile's instructions, the tool's note)", "link": None,
                            "text": rest}] if rest else [])]


def _size(jpeg: bytes) -> tuple[int, int]:
    try:
        with Image.open(io.BytesIO(jpeg)) as im:
            return im.size
    except (OSError, ValueError, Image.DecompressionBombError):
        return 0, 0


def _warning(t: Try, sizes: list[tuple[int, int]]) -> str | None:
    if t.provider == "openai" and t.detail in ("low", "medium") and sizes:
        w, h = max(sizes, key=lambda s: max(s))
        if max(w, h) > OPENAI_LOW:
            return (f"Sent at OpenAI's low detail: a {w} × {h} px picture is shrunk to fit {OPENAI_LOW} px "
                    f"({max(w, h) / OPENAI_LOW:.1f}× smaller), so small things in it may not be readable.")
    return None


def _save(session: Session, req: Request) -> None:
    last = next((t for t in reversed(req.tries) if t.ok), req.tries[-1])
    sizes = [_size(p) for p in last.pictures]
    rid = uuid.uuid4().hex
    folder = ROOT / rid
    for n, jpeg in enumerate(last.pictures):
        files.write_bytes(folder / f"{n}.jpg", jpeg)
    labels = req.labels + [f"Picture {n + 1}" for n in range(len(req.labels), len(last.pictures))]
    tries = [{"profile": t.profile, "provider": t.provider,
              "model": t.model, "ok": t.ok, "outcome": t.outcome, "ms": t.ms} for t in req.tries]
    status = "failed" if req.error or not last.ok else "fell back" if len(req.tries) > 1 or req.notes else "ok"
    row = LlmRequest(
        id=rid, at=req.at, source=req.source, task=req.task, link=req.link, camera=req.camera, status=status,
        error=req.error or (None if last.ok else last.outcome),
        provider=last.provider, model=last.model, profile=last.profile,
        detail=last.detail if last.pictures else None, thinking=last.thinking, prompt=last.prompt,
        parts=_parts(req, last.prompt), answer_schema=last.schema, reply=last.reply, outcome=req.outcome,
        tries=[*({"profile": n, "provider": None, "model": None, "ok": False, "outcome": "passed over", "ms": 0}
                 for n in req.notes), *tries],
        pictures=[{"label": labels[n], "width": w, "height": h, "size": len(jpeg)}
                  for n, ((w, h), jpeg) in enumerate(zip(sizes, last.pictures, strict=True))],
        pictures_kept=bool(last.pictures), ms=sum(t.ms for t in req.tries),
        tokens_in=sum(t.tokens_in for t in req.tries), tokens_out=sum(t.tokens_out for t in req.tries),
        cost=None if all(t.cost is None for t in req.tries) else sum(t.cost or 0.0 for t in req.tries),
        warning=_warning(last, sizes))
    session.add(row)
    # Phase 7b: what the requests add up to is counted by the HiroLeague core (Logs → AI usage), not here.
    session.commit()
    _prune(session)
    bus.publish(NOTICE)


def _prune(session: Session, now: datetime | None = None) -> None:
    """Drop rows older than KEEP_DAYS and pictures older than PICTURE_DAYS; at most once every PRUNE_EVERY."""
    global _pruned_at
    now = now or datetime.now(UTC)
    if _pruned_at and now - _pruned_at < PRUNE_EVERY:
        return
    _pruned_at = now
    old = now - timedelta(days=PICTURE_DAYS)
    for row in session.exec(select(LlmRequest).where(col(LlmRequest.at) < old, col(LlmRequest.pictures_kept).is_(True))):
        shutil.rmtree(ROOT / row.id, ignore_errors=True)
        row.pictures_kept = False
        session.add(row)
    session.exec(delete(LlmRequest).where(col(LlmRequest.at) < now - timedelta(days=KEEP_DAYS)))
    session.commit()


def picture(rid: str, n: int) -> bytes | None:
    """A request's picture, while it's kept."""
    path = ROOT / rid / f"{n}.jpg"
    if not rid.isalnum() or not path.is_file():
        return None
    return path.read_bytes()
