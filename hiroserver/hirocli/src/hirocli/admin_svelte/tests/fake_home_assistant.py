"""A small fake Home Assistant on 127.0.0.1, for "Sign in with Home Assistant" (services/home_assistant.py): its
WebSocket (auth, person/list, config/auth/list for an administrator's token, auth/current_user), /auth/token and
/auth/revoke. It runs in a thread of its own, so a test's sync client and the core's calls both reach it."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from typing import Any

import uvicorn
from urllib.parse import parse_qs

from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import JSONResponse

VERSION = "2026.11.2"


@dataclass
class FakeHa:
    admin_token: str = "owner-long-lived"
    plain_token: str = "not-an-admin"
    people: list[dict[str, Any]] = field(default_factory=lambda: [
        {"id": "michel", "name": "Michel", "user_id": "u-michel"},
        {"id": "mark", "name": "Mark", "user_id": "u-mark"},
        {"id": "guest", "name": "Guest", "user_id": "u-guest"},
        {"id": "cat", "name": "The cat", "user_id": None},  # a person with no login
    ])
    users: dict[str, str] = field(default_factory=lambda: {"u-michel": "michel", "u-mark": "mark", "u-guest": "guest"})
    codes: dict[str, str] = field(default_factory=dict)  # a login code → the HA user it signs in
    revoked: list[str] = field(default_factory=list)
    url: str = ""

    def app(self) -> FastAPI:
        app = FastAPI()
        person_tokens: dict[str, str] = {}

        @app.post("/auth/token")
        async def token(request: Request) -> Any:
            form = await _form(request)
            user = self.codes.pop(form.get("code", ""), None)
            if user is None or form.get("grant_type") != "authorization_code" or not form.get("client_id"):
                return JSONResponse({"error": "invalid_request"}, status_code=400)
            person_tokens[f"access-{user}"] = user
            return {"access_token": f"access-{user}", "refresh_token": f"refresh-{user}", "token_type": "Bearer"}

        @app.post("/auth/revoke")
        async def revoke(request: Request) -> Any:
            self.revoked.append((await _form(request)).get("token", ""))
            return {}

        @app.websocket("/api/websocket")
        async def ws(socket: WebSocket) -> None:
            await socket.accept()
            await socket.send_json({"type": "auth_required", "ha_version": VERSION})
            said = await socket.receive_json()
            given = said.get("access_token")
            if given not in (self.admin_token, self.plain_token) and given not in person_tokens:
                await socket.send_json({"type": "auth_invalid", "message": "Invalid access token"})
                await socket.close()
                return
            await socket.send_json({"type": "auth_ok", "ha_version": VERSION})
            while True:
                ask = await socket.receive_json()
                kind, ask_id = ask.get("type"), ask.get("id")
                if kind == "person/list":
                    result: Any = {"storage": self.people, "config": []}
                elif kind == "config/auth/list" and given == self.admin_token:
                    result = [{"id": uid, "username": name, "name": name.title()} for uid, name in self.users.items()]
                elif kind == "auth/current_user" and given in person_tokens:
                    uid = person_tokens[given]
                    result = {"id": uid, "name": self.users[uid].title(), "is_owner": False}
                else:
                    await socket.send_json({"id": ask_id, "type": "result", "success": False,
                                            "error": {"code": "unauthorized", "message": "Unauthorized"}})
                    continue
                await socket.send_json({"id": ask_id, "type": "result", "success": True, "result": result})

        return app


async def _form(request: Request) -> dict[str, str]:
    """A posted form, read by hand (the core doesn't carry python-multipart for FastAPI's Form)."""
    return {k: v[0] for k, v in parse_qs((await request.body()).decode()).items()}


class RunningFakeHa:
    """The fake served on a free port in a thread; `stop()` ends it."""

    def __init__(self, fake: FakeHa) -> None:
        self.fake = fake
        self._server = uvicorn.Server(uvicorn.Config(fake.app(), host="127.0.0.1", port=0, log_level="warning",
                                                     ws="websockets-sansio"))
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        asyncio.run(self._server.serve())

    def start(self) -> FakeHa:
        self._thread.start()
        for _ in range(500):
            if self._server.started:
                break
            threading.Event().wait(0.01)
        port = self._server.servers[0].sockets[0].getsockname()[1]
        self.fake.url = f"http://127.0.0.1:{port}"
        return self.fake

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(5)
