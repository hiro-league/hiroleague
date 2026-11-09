"""AI asks for extensions — the ``ai.ask`` and ``ai.profiles`` requests (Phase 7a).

An extension (HomeHiro first) asks the core's AI instead of keeping its own keys, models and
limits: ``ai.ask`` names one of the extension's declared uses (``ExtensionInfo.uses``), and the
core asks the profile the admin picked for ``"<extension>:<use>"`` (or the profile the ask names:
a copy's own pick), walking its fallbacks (services/ai_ask). ``ai.profiles`` lists the profiles
and this extension's use → profile map for its pickers. Extensions only: the app can't spend the
home's AI budget by being connected.

Errors answer the contract's codes (``no_profile``, ``budget``, ``busy``, ``failed``, ``invalid``)
as the response's error code, through ``RequestRefused``.
"""

from __future__ import annotations

import asyncio
from typing import Any

from hiro_channel_sdk.constants import AI_ERROR_INVALID, METHOD_AI_ASK, METHOD_AI_PROFILES
from hiro_commons.log import Logger

from ..domain.credential_store import CredentialStore
from ..domain.extensions import get_paired_extension
from ..domain.people import get_person
from ..domain.workspace import workspace_id_for_path
from ..services.ai_ask import AskError, extension_use_map, get_ask_runner, profile_rows
from ..services.ai_ask.params import ask_request_from_params
from .request_handler import EXTENSIONS_ONLY, RequestContext, RequestRefused

log = Logger.get("AI.ASK")


async def _caller_name(ctx: RequestContext) -> str:
    """The calling extension's name (the first half of its use keys)."""
    extension_id = ctx.msg.routing.sender_id
    manager = ctx.server_ctx.extension_manager
    if manager is not None:
        live = manager.snapshot().get(extension_id)
        if live and live.get("name"):
            return str(live["name"])
    paired = await asyncio.to_thread(get_paired_extension, ctx.workspace_path, extension_id)
    if paired is None or not paired.name:
        raise RequestRefused(AI_ERROR_INVALID, "This extension isn't paired with the core.")
    return paired.name


async def handle_ai_ask(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    name = await _caller_name(ctx)
    use = params.get("use")
    if not isinstance(use, str) or not use.strip():
        raise RequestRefused(AI_ERROR_INVALID, "use is required (one of the extension's declared uses).")
    use_key = f"{name}:{use.strip()}"
    try:
        request = ask_request_from_params(params, use_key=use_key, who=name)
        # Phase 7b: a person the core doesn't know would file the ask's usage under nobody.
        if request.person_id and await asyncio.to_thread(get_person, ctx.workspace_path, request.person_id) is None:
            raise AskError(AI_ERROR_INVALID, f"There's no person {request.person_id!r} in the family list.")
        answer = await get_ask_runner(ctx.workspace_path).ask(request, prefs=ctx.server_ctx.preferences.current)
    except AskError as exc:
        raise RequestRefused(exc.code, exc.message) from exc
    return answer.to_dict()


async def handle_ai_profiles(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    del params
    name = await _caller_name(ctx)
    prefs = ctx.server_ctx.preferences.current
    rows = await asyncio.to_thread(_profile_rows, ctx)
    return {"profiles": rows, "uses": extension_use_map(prefs, name)}


def _profile_rows(ctx: RequestContext) -> list[dict[str, Any]]:
    wid = workspace_id_for_path(ctx.workspace_path)
    store = CredentialStore(ctx.workspace_path, wid) if wid is not None else None
    return profile_rows(ctx.workspace_path, ctx.server_ctx.preferences.current, store)


AI_REQUEST_HANDLERS: tuple[tuple[str, Any, frozenset[str]], ...] = (
    (METHOD_AI_ASK, handle_ai_ask, EXTENSIONS_ONLY),
    (METHOD_AI_PROFILES, handle_ai_profiles, EXTENSIONS_ONLY),
)
