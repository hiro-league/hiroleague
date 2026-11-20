"""Every admin request is a story, as every app's page request is (the backend kit's `stories.py`): a request that
brings a W3C `traceparent` header (the UI kit's client sends one) continues that story, any other starts one. What the
request does then carries the id, and an action the admin names (trying a profile, a voice, an image: the logging
plan's phase 6a) is listed as a story. The request's own step is at DEBUG: the admin polls, so it writes nothing at INFO
unless it is named.
"""

from __future__ import annotations

import logging

from hiro_commons.logging_foundation import story
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class AdminStories:
    """Plain ASGI, so streamed answers flow as they are."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers") or []}
        with story.begin("http.request", parent=headers, area="ADMIN.REQUESTS", level=logging.DEBUG,
                         method=scope.get("method", ""), path=scope.get("path", "")) as step:
            carried = step.carry()

            async def answer(message: Message) -> None:
                if message["type"] == "http.response.start":
                    step.set(status=message["status"])
                    message = {**message, "headers": [*message.get("headers", []),
                                                      (story.TRACEPARENT.encode(), carried.encode())]}
                await send(message)

            await self.app(scope, receive, answer)
