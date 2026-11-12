"""Logs → LLM requests (llm/recorder.py keeps them).

- `GET /api/logs/llm`: the requests, newest first, by what asked, camera, problems only, or words in them.
- `GET /api/logs/llm/{id}`: one, whole: its words by part and as sent, its schema, its reply, each model asked.
- `GET /api/logs/llm/{id}/pictures/{n}`: one of its pictures, while they are kept.

Open pages hear "llm" when a request is kept.
"""

import os
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import or_
from sqlmodel import Session, col, select

from ..db import get_session
from ..errors import NotFound
from .models import LlmRequest
from . import recorder

router = APIRouter(prefix="/api/logs/llm")

LIMIT = 300  # requests per answer at most
SHORT_REPLY = 400  # characters of a reply in the list
Source = Literal["Ask a camera", "Ask now", "Write text", "Try it", "Other"]


class LlmRequestRow(BaseModel):
    id: str
    at: datetime
    source: str
    task: str
    camera: str | None
    status: str
    error: str | None
    model: str | None
    profile: str | None
    pictures: int
    pictures_kept: bool
    reply: str | None  # its start
    ms: int
    cost: float | None
    warning: str | None


class LlmRequests(BaseModel):
    requests: list[LlmRequestRow]
    more: bool  # older ones match too
    keep_days: int
    picture_days: int
    disk: int  # bytes the pictures take
    cameras: list[str]  # the cameras of the kept requests (the camera filter)


class LlmRequestOut(BaseModel):
    id: str
    at: datetime
    source: str
    task: str
    link: str | None
    camera: str | None
    status: str
    error: str | None
    provider: str | None
    model: str | None
    profile: str | None
    detail: str | None
    thinking: str | None
    prompt: str
    parts: list[dict[str, Any]]  # {label, link, text}
    answer_schema: dict[str, Any]
    reply: str | None
    outcome: str | None
    tries: list[dict[str, Any]]  # {profile, provider, model, ok, outcome, ms}
    pictures: list[dict[str, Any]]  # {label, width, height, size}
    pictures_kept: bool
    ms: int
    tokens_in: int
    tokens_out: int
    cost: float | None
    warning: str | None


def _disk() -> int:
    total = 0
    for folder, _dirs, names in os.walk(recorder.ROOT):
        total += sum(os.path.getsize(os.path.join(folder, n)) for n in names)
    return total


@router.get("")
def requests(source: Source | None = None, camera: str | None = Query(None, max_length=100), problems: bool = False,
             q: str = Query("", max_length=200), session: Session = Depends(get_session)) -> LlmRequests:
    query = select(LlmRequest).order_by(col(LlmRequest.at).desc())
    if source:
        query = query.where(LlmRequest.source == source)
    if camera:
        query = query.where(LlmRequest.camera == camera)
    if problems:
        query = query.where(or_(col(LlmRequest.status) != "ok", col(LlmRequest.warning).is_not(None)))
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.where(or_(col(LlmRequest.task).ilike(like), col(LlmRequest.camera).ilike(like),
                                col(LlmRequest.model).ilike(like), col(LlmRequest.prompt).ilike(like),
                                col(LlmRequest.reply).ilike(like), col(LlmRequest.error).ilike(like)))
    rows = session.exec(query.limit(LIMIT + 1)).all()
    out = [LlmRequestRow(id=r.id, at=r.at, source=r.source, task=r.task, camera=r.camera, status=r.status, error=r.error,
                         model=r.model, profile=r.profile, pictures=len(r.pictures), pictures_kept=r.pictures_kept,
                         reply=(r.reply or "")[:SHORT_REPLY] or None, ms=r.ms, cost=r.cost, warning=r.warning)
           for r in rows[:LIMIT]]
    cameras = session.exec(select(LlmRequest.camera).where(col(LlmRequest.camera).is_not(None)).distinct()).all()
    return LlmRequests(requests=out, more=len(rows) > LIMIT, keep_days=recorder.KEEP_DAYS,
                       picture_days=recorder.PICTURE_DAYS, disk=_disk(), cameras=sorted(c for c in cameras if c))


@router.get("/{rid}")
def request(rid: str, session: Session = Depends(get_session)) -> LlmRequestOut:
    r = session.get(LlmRequest, rid)
    if r is None:
        raise NotFound(f"That request isn't in the log (they are kept {recorder.KEEP_DAYS} days).")
    return LlmRequestOut.model_validate(r, from_attributes=True)


@router.get("/{rid}/pictures/{n}", response_class=Response, responses={200: {"content": {"image/jpeg": {}}}})
def picture(rid: str, n: int) -> Response:
    jpeg = recorder.picture(rid, n)
    if jpeg is None:
        raise NotFound(f"That picture isn't kept any more (pictures are kept {recorder.PICTURE_DAYS} days).")
    return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "max-age=31536000, immutable"})
