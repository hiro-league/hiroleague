"""Every page request is a story: the logging plan's one id, from a page through the app to the core and on.

A request that brings a W3C `traceparent` header continues that story (the page's own, once pages report: the plan's
phase 8); any other starts one. Everything the request does then carries the id (the foundation's `story`): the app's
lines, its requests to the core (the SDK puts the id in each frame), the core's lines for them, another app's answer,
and the LLM request it records. The answer gives the id back in its own `traceparent` header, so a page can name it.

The request is a step at DEBUG (`<app>.requests`: "http.request took 12 ms", with its method, path and status): pages
poll, so it writes nothing at the usual INFO. `errors.install` puts it on every kit app.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi import FastAPI, Request
from hiro_commons.logging_foundation import story
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from . import identity

STATE = "story"  # scope["state"]["story"]: the request's step as a traceparent, for what runs outside this middleware


class Stories:
    """Plain ASGI (not BaseHTTPMiddleware), so streamed answers (/api/events) flow as they are."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers") or []}
        with story.begin("http.request", parent=headers, area=identity.logger("requests").name, level=logging.DEBUG,
                         method=scope.get("method", ""), path=scope.get("path", "")) as step:
            carried = step.carry()
            scope.setdefault("state", {})[STATE] = carried

            async def answer(message: Message) -> None:
                if message["type"] == "http.response.start":
                    step.set(status=message["status"])
                    message = {**message, "headers": [*message.get("headers", []),
                                                      (story.TRACEPARENT.encode(), carried.encode())]}
                await send(message)

            await self.app(scope, receive, answer)


def install(app: FastAPI) -> None:
    app.add_middleware(Stories)


@contextmanager
def of(request: Request) -> Iterator[Any]:
    """Back inside the request's story, for a handler that runs outside this middleware (Starlette's crash handler):
    its lines carry the request's id. No line of its own."""
    with story.begin("http.request", parent=request.scope.get("state", {}).get(STATE), line=False) as step:
        yield step
