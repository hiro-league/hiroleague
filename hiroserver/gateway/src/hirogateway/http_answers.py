"""What the gateway says to a request that isn't a WebSocket: a browser, a health check, a port scan.

Its port takes WebSocket connections only. websockets answers anything else ``426`` and logs "opening handshake failed"
at ERROR with a traceback, and the core's log store shows each one as a problem. So a plain HTTP request gets a short
answer here (``/health`` says ``ok``), and a handshake refused for any other reason (a request websockets can't read)
is one line at INFO.
"""

from __future__ import annotations

import http
import logging

from hiro_commons.log import Logger
from websockets.asyncio.server import ServerConnection
from websockets.http11 import Request, Response

log = Logger.get("GATEWAY")

HEALTH_PATH = "/health"
WEBSOCKETS_LOGGER = "websockets.server"
_HANDSHAKE_FAILED = "opening handshake failed"
_PAGE = "Hiro gateway: this address takes WebSocket connections from Hiro's devices.\n"


def answer_plain_http(connection: ServerConnection, request: Request) -> Response | None:
    """websockets' ``process_request``: None lets a WebSocket handshake go on; a plain request gets its answer."""
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return None
    path = request.path.split("?", 1)[0]  # a query may hold a key: never logged
    if path == HEALTH_PATH:
        return connection.respond(http.HTTPStatus.OK, "ok\n")
    log.info("Gateway: a plain HTTP request answered (this port takes WebSockets)", path=path)
    return connection.respond(http.HTTPStatus.UPGRADE_REQUIRED, _PAGE)


class QuietRefusedHandshake(logging.Filter):
    """Turns websockets' "opening handshake failed" ERROR (with its traceback) into one INFO line of the gateway's."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.getMessage() != _HANDSHAKE_FAILED:
            return True
        exc = record.exc_info[1] if record.exc_info else None
        reason = exc.__cause__ or exc if exc is not None else None
        log.info(
            "Gateway: a connection that wasn't a WebSocket was refused",
            reason=type(reason).__name__ if reason is not None else "unknown",
            detail=str(reason) if reason is not None else "",
        )
        return False


def install_quiet_handshakes() -> None:
    logger = logging.getLogger(WEBSOCKETS_LOGGER)
    if not any(isinstance(f, QuietRefusedHandshake) for f in logger.filters):
        logger.addFilter(QuietRefusedHandshake())
