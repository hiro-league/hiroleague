"""A plain HTTP request to the gateway's port gets a short answer and no ERROR; a WebSocket still opens."""

from __future__ import annotations

import asyncio
import logging

import pytest
import websockets
from websockets.asyncio.server import ServerConnection

from hirogateway import http_answers
from hirogateway.http_answers import answer_plain_http, install_quiet_handshakes


async def _echo(ws: ServerConnection) -> None:
    async for message in ws:
        await ws.send(message)


async def _http(port: int, raw: bytes) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(raw)
    await writer.drain()
    data = await reader.read()
    writer.close()
    return data


async def _exchange(raws: list[bytes]) -> tuple[list[bytes], str]:
    install_quiet_handshakes()
    async with websockets.serve(_echo, "127.0.0.1", 0, process_request=answer_plain_http) as server:
        port = server.sockets[0].getsockname()[1]
        answers = [await _http(port, raw) for raw in raws]
        async with websockets.connect(f"ws://127.0.0.1:{port}/") as ws:
            await ws.send("hi")
            echoed = await ws.recv()
    return answers, str(echoed)


def test_plain_http_gets_an_answer_and_the_websocket_still_opens(caplog: pytest.LogCaptureFixture, monkeypatch) -> None:
    infos: list[str] = []
    monkeypatch.setattr(http_answers.log, "info", lambda msg, **kw: infos.append(msg))
    caplog.set_level(logging.DEBUG, logger="websockets.server")
    answers, echoed = asyncio.run(_exchange([
        b"GET /?token=secret HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n",
        b"GET /health HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n",
        b"\x16\x03\x01 not http at all\r\n\r\n",  # a TLS hello or a scanner: websockets can't read it
    ]))
    assert answers[0].startswith(b"HTTP/1.1 426") and b"Hiro gateway" in answers[0]
    assert answers[1].startswith(b"HTTP/1.1 200") and answers[1].endswith(b"ok\n")
    assert echoed == "hi"
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]  # before: ERROR with a traceback
    assert infos == [
        "Gateway: a plain HTTP request answered (this port takes WebSockets)",
        "Gateway: a connection that wasn't a WebSocket was refused",
    ]
