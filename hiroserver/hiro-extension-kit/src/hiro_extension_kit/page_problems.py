"""A page's problems, in its app's log: the logging plan's phase 8 (browser pages join as sources).

The UI kit reports what goes wrong in a page (`$kit/api/problems.ts`): an error nobody caught, a page that stopped
drawing, a page that couldn't open, and a call to this backend that got no answer or a 5xx. It posts them here in small
batches; each becomes one line of the app's own log (`<app>.page`), under the story it belongs to: a failed call's
own story (the page sends each call's `traceparent`, so the backend's lines for that call carry the same id), else a
story the page started for the error. From the app's file the line goes on to the core like any other.

What a page may say is fixed here, field by field, and cut to size: the page's path (never its query, which can hold a
sign-in code), the error's type, message and stack, and for a call its method, path and status. Nothing else from a
page reaches a line. `signed_in`: a page someone with a role has open (the kit's rule, auth/guard.py).
"""

import logging
import time
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, FastAPI
from hiro_commons.logging_foundation import story
from pydantic import BaseModel, Field

from . import identity

router = APIRouter()

PATH = "/api/page-problems"
PER_MINUTE = 60  # lines a minute from every page together; past it a minute's report says how many were dropped
_window = {"start": 0.0, "count": 0, "dropped": 0}


class PageProblem(BaseModel):
    """One problem a page saw."""

    kind: Literal["error", "page", "request"]  # an uncaught error; a page that stopped drawing or couldn't open; a call
    level: Literal["WARNING", "ERROR"] = "ERROR"
    message: str = Field(max_length=2000)  # what went wrong, as the page has it
    error_type: str = Field("", max_length=200)  # the error's name: TypeError, ApiError...
    stack: str = Field("", max_length=8000)
    page: str = Field("", max_length=500)  # the page's path, with no query
    traceparent: str = Field("", max_length=100)  # the story it belongs to: the call's own, or one the page started
    at: datetime | None = None  # when the page saw it (the line's own time is when it arrived)
    count: int = Field(1, ge=1, le=10_000)  # the same problem again, before the page sent it
    # A failed call (kind "request")
    method: str = Field("", max_length=10)
    path: str = Field("", max_length=500)
    status: int | None = None  # 0: no answer (unreachable, or it ran out of time)


class PageProblemsIn(BaseModel):
    problems: list[PageProblem] = Field(max_length=20)


class PageProblemsOut(BaseModel):
    kept: int  # problems written to the log (the rest went over the minute's limit)


def _cut(text: str, size: int) -> str:
    return text if len(text) <= size else text[: size - 1] + "…"


def _no_query(path: str) -> str:
    """A path with its query cut off: a query can hold a sign-in code."""
    return _cut(path.split("?", 1)[0].split("#", 1)[0], 200)


def _sentence(p: PageProblem) -> str:
    message = _cut(" ".join(p.message.split()), 300)
    page = _no_query(p.page) or "?"
    if p.kind == "request":
        answer = "got no answer" if not p.status else f"answered {p.status}"
        return f"Page {page}: {p.method} {_no_query(p.path)} {answer}: {message}"
    what = "stopped working" if p.kind == "page" else "had an error"
    return f"Page {page} {what}: {p.error_type + ': ' if p.error_type else ''}{message}"


def _room(log: logging.Logger) -> bool:
    """One more line this minute? Says once a minute how many it dropped, so a page in a loop can't fill the file."""
    now = time.monotonic()
    if now - _window["start"] >= 60:
        if _window["dropped"]:
            log.warning("Pages reported %d more problems in a minute; dropped past %d", _window["dropped"], PER_MINUTE,
                        extra={"dropped": _window["dropped"]})
        _window.update(start=now, count=0, dropped=0)
    if _window["count"] >= PER_MINUTE:
        _window["dropped"] += 1
        return False
    _window["count"] += 1
    return True


def write(p: PageProblem) -> None:
    """The problem's line, in the app's log, under its story."""
    log = identity.logger("page")
    fields: dict = {"page": _no_query(p.page), "problem": p.kind}
    if p.at is not None:
        fields["seen_at"] = p.at.isoformat()
    if p.count > 1:
        fields["count"] = p.count
    if p.kind == "request":
        fields.update(method=p.method, path=_no_query(p.path), status=p.status or 0)
    if p.error_type:
        fields["exception.type"] = p.error_type
    fields["exception.message"] = _cut(p.message, 2000)
    if p.stack:
        fields["exception.stacktrace"] = p.stack
    level = logging.ERROR if p.level == "ERROR" else logging.WARNING
    if not p.traceparent:  # a page that sent none (StudyHiro's own client): the report's own request's story
        log.log(level, "%s", _sentence(p), extra={"attributes": fields})
        return
    with story.begin("page.problem", parent=p.traceparent, line=False):  # the problem's own story, continued
        log.log(level, "%s", _sentence(p), extra={"attributes": fields})


@router.post(PATH, response_model=PageProblemsOut)
async def page_problems(body: PageProblemsIn) -> PageProblemsOut:
    log = identity.logger("page")
    kept = 0
    for p in body.problems:
        if _room(log):
            write(p)
            kept += 1
    return PageProblemsOut(kept=kept)


def install(app: FastAPI) -> None:
    """Every kit app takes its pages' problems (errors.install puts it on, before the app's own routes)."""
    app.include_router(router)
