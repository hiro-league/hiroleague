"""AI asks for extensions — the ``ai.ask``, ``ai.chat`` and ``ai.profiles`` requests (Phase 7a).

An extension (HomeHiro first) asks the core's AI instead of keeping its own keys, models and
limits: ``ai.ask`` names one of the extension's declared uses (``ExtensionInfo.uses``), and the
core asks the profile the admin picked for ``"<extension>:<use>"`` (or the profile the ask names:
a copy's own pick), walking its fallbacks (services/ai_ask). ``ai.profiles`` lists the profiles
and this extension's use → profile map for its pickers. ``ai.chat`` is ``ai.ask`` for a conversation
whose model may call the extension's tools (EvalHiro runs Hiro's recall agent through it): the same profile
walk, limits and AI usage. Extensions only: the app can't spend the home's AI budget by being connected.

Errors answer the contract's codes (``no_profile``, ``budget``, ``busy``, ``failed``, ``invalid``)
as the response's error code, through ``RequestRefused``.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from hiro_channel_sdk.constants import AI_ERROR_FAILED, AI_ERROR_INVALID, METHOD_AI_ASK, METHOD_AI_CHAT, METHOD_AI_PROFILES
from hiro_commons.log import Logger

from ..domain.credential_store import CredentialStore
from ..domain.extensions import get_paired_extension
from ..domain.people import get_person
from ..domain.workspace import workspace_id_for_path
from ..services import fakes
from ..services.ai_ask import AskError, extension_use_map, get_ask_runner, profile_rows
from ..services.ai_ask.folders import check_folder
from ..services.ai_ask.params import ask_request_from_params, chat_request_from_params
from ..services.ai_ask.runner import AskAnswer, AskRequest
from ..services.ai_usage import UsageCall, record_async
from .request_handler import EXTENSIONS_ONLY, RequestContext, RequestRefused, gate

log = Logger.get("AI.ASK")

FAKE = "fake"  # the switchboard's mode a stand-in answers


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


async def _checked_folder(folder: str, name: str, use: str, ctx: RequestContext) -> Path:
    """The folder an ask names, if this extension's use declares it and the admin allowed it (ai_ask/folders.py)."""
    paired = await asyncio.to_thread(get_paired_extension, ctx.workspace_path, ctx.msg.routing.sender_id)
    declared = {u["id"]: u for u in (paired.declared_uses() if paired else [])}
    allowed = ctx.server_ctx.preferences.current.ai.folders.get(name, [])
    return await asyncio.to_thread(
        check_folder, folder, allowed, extension=name, use=use, use_reads_folders=bool(declared.get(use, {}).get("folder"))
    )


async def _fake_answer(request: AskRequest, ctx: RequestContext) -> dict[str, Any]:
    """A test environment's stand-in for the AI (services/fakes.py): a canned text, or the smallest JSON of the shape
    asked for; a conversation gets it as the model's reply, with no tool calls. Counted in AI usage at no cost, under
    the provider "fake"."""
    words = json.dumps(fakes.from_schema(request.schema)) if request.schema else fakes.text()
    await record_async(ctx.workspace_path, UsageCall(
        kind="question", source=request.source, use=request.use_id, profile_id=fakes.PROVIDER,
        profile_name=fakes.PROFILE_NAME, provider=fakes.PROVIDER, model=fakes.MODEL, billing="local",
        person_id=request.person_id, label=request.label))
    log.info(f"✅ AI answered by the stand-in — {request.who} · {request.use}", schema=bool(request.schema))
    return AskAnswer(
        text=words, profile_id=fakes.PROVIDER, profile_name=fakes.PROFILE_NAME, provider=fakes.PROVIDER,
        model=fakes.MODEL, plan=False, ms=0, tokens=0, tokens_in=0, tokens_out=0, cost=0.0, estimate=None,
        notes=["AI is fake in this environment: the switchboard's stand-in answered."], tries=[],
        message={"content": words, "tool_calls": []} if request.messages is not None else None,
    ).to_dict()


async def handle_ai_ask(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    mode = gate("ai", AI_ERROR_FAILED, fakes=True)  # a test environment's switchboard: asked for every app, here
    name = await _caller_name(ctx)
    use = params.get("use")
    if not isinstance(use, str) or not use.strip():
        raise RequestRefused(AI_ERROR_INVALID, "use is required (one of the extension's declared uses).")
    use_key = f"{name}:{use.strip()}"
    try:
        request = ask_request_from_params(params, use_key=use_key, who=name)
        if mode == FAKE:  # the stand-in answers: no profile, no provider, nothing paid
            return await _fake_answer(request, ctx)
        if request.folder:
            request = replace(request, folder=str(await _checked_folder(request.folder, name, use.strip(), ctx)))
        # Phase 7b: a person the core doesn't know would file the ask's usage under nobody.
        if request.person_id and await asyncio.to_thread(get_person, ctx.workspace_path, request.person_id) is None:
            raise AskError(AI_ERROR_INVALID, f"There's no person {request.person_id!r} in the family list.")
        answer = await get_ask_runner(ctx.workspace_path).ask(request, prefs=ctx.server_ctx.preferences.current)
    except AskError as exc:
        raise RequestRefused(exc.code, exc.message) from exc
    return answer.to_dict()


async def handle_ai_chat(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    mode = gate("ai", AI_ERROR_FAILED, fakes=True)
    name = await _caller_name(ctx)
    use = params.get("use")
    if not isinstance(use, str) or not use.strip():
        raise RequestRefused(AI_ERROR_INVALID, "use is required (one of the extension's declared uses).")
    try:
        request = chat_request_from_params(params, use_key=f"{name}:{use.strip()}", who=name)
        if mode == FAKE:
            return await _fake_answer(request, ctx)
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
    (METHOD_AI_CHAT, handle_ai_chat, EXTENSIONS_ONLY),
    (METHOD_AI_PROFILES, handle_ai_profiles, EXTENSIONS_ONLY),
)
