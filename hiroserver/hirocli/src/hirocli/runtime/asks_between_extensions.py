"""Extensions ask each other through the core (``extensions.ask``, the plan's Phase 9b).

An extension never connects to another one. It asks the core, which passes the ask on when the asked extension is
connected and offers that method (``ExtensionInfo.offers``: ``knows`` and ``can_do``, each ``{"method", ...}``), and
hands back its answer as it is (an error too). The asked extension gets the params plus who asked (``ASKED_BY``), so
it can answer or refuse per asker. First uses: Home asks NetHiro for a person's internet use; NetHiro asks Home for the
router's counters (Home keeps the one Home Assistant connection). Contract: hiro_channel_sdk.constants.
"""

from __future__ import annotations

from typing import Any

from hiro_channel_sdk.constants import (
    ASK_ERROR_NOT_OFFERED,
    ASK_TIMEOUT_MAX_SECONDS,
    ASKED_BY,
    EXTENSION_REQUEST_TIMEOUT_SECONDS,
    METHOD_EXTENSIONS_ASK,
)
from hiro_channel_sdk.extension import ExtensionRequestError
from hiro_commons.log import Logger

from .ai_for_extensions import _caller_name
from .request_handler import EXTENSIONS_ONLY, RequestContext, RequestRefused

log = Logger.get("EXTENSIONS")

OFFER_SLOTS = ("knows", "can_do")  # the offers an extension answers asks for


def offered_methods(info: dict[str, Any]) -> set[str]:
    """The request methods an extension offers to other extensions (``offers.knows`` and ``offers.can_do``)."""
    offers = info.get("offers") or {}
    if not isinstance(offers, dict):
        return set()
    return {
        str(item["method"])
        for slot in OFFER_SLOTS
        for item in offers.get(slot) or []
        if isinstance(item, dict) and item.get("method")
    }


def _target(manager: Any, name: str) -> tuple[str, dict[str, Any]] | None:
    """The connected extension called ``name``: its id and the info it signed in with; None when not connected."""
    for extension_id, live in manager.snapshot().items():
        if str(live.get("name") or "") == name:
            return extension_id, dict(live.get("info") or {})
    return None


def _timeout(params: dict[str, Any]) -> float:
    try:
        asked = float(params.get("timeout") or EXTENSION_REQUEST_TIMEOUT_SECONDS)
    except (TypeError, ValueError):
        asked = EXTENSION_REQUEST_TIMEOUT_SECONDS
    return max(1.0, min(asked, ASK_TIMEOUT_MAX_SECONDS))


async def handle_extensions_ask(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    """Pass one extension's ask on to another, when that one is connected and offers the method."""
    to = str(params.get("to") or "").strip()
    method = str(params.get("method") or "").strip()
    inner = params.get("params") or {}
    if not to or not method or not isinstance(inner, dict):
        raise RequestRefused("invalid_params", "extensions.ask needs to, method and (optional) params {…}")
    asker = await _caller_name(ctx)
    if to == asker:
        raise RequestRefused("invalid_params", "An extension answers its own questions without the core.")
    manager = ctx.server_ctx.extension_manager
    target = _target(manager, to) if manager is not None else None
    if target is None:
        raise RequestRefused("not_connected", f"{to} isn't connected to HiroLeague now.")
    extension_id, info = target
    if method not in offered_methods(info):
        raise RequestRefused(ASK_ERROR_NOT_OFFERED, f"{to} doesn't offer {method}.")
    log.info(f"⬆️ Extension ask passed on — {asker} → {to} · {method}")
    try:
        return await manager.request(extension_id, method, {**inner, ASKED_BY: asker}, timeout=_timeout(params))
    except ExtensionRequestError as exc:
        # The asked extension's own answer (or not_connected / timeout) goes back to the asker as it is.
        log.warning(f"⚠️ Extension ask not answered — {asker} → {to} · {method}", error=exc.message, code=exc.code)
        raise RequestRefused(exc.code, exc.message) from exc


ASK_REQUEST_HANDLERS: tuple[tuple[str, Any, frozenset[str]], ...] = (
    (METHOD_EXTENSIONS_ASK, handle_extensions_ask, EXTENSIONS_ONLY),
)
