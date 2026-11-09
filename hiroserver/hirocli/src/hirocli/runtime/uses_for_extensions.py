"""An extension picks the profile each of its own uses asks with — ``ai.uses.set`` / ``voice.uses.set`` (Phase 7b).

"HomeHiro picks, the core edits": HomeHiro's AI and voice pages pick a profile for each of HomeHiro's uses,
and the pick is saved here, in ``ai.uses`` / ``voice.uses`` (the same keys the Catalog's Uses tab writes).
An extension may set only its own uses, and only ones it declared (``ExtensionInfo.uses`` / ``voice_uses``);
the profile must exist (the preferences check it). Profiles themselves are edited only in the core's admin.
Extensions only.
"""

from __future__ import annotations

import asyncio
from typing import Any

from hiro_channel_sdk.constants import (
    AI_ERROR_INVALID,
    METHOD_AI_USES_SET,
    METHOD_VOICE_USES_SET,
)
from hiro_commons.log import Logger
from pydantic import ValidationError

from ..domain.extensions import declared_uses, get_paired_extension
from .ai_for_extensions import _caller_name
from .preferences_runtime import PreferencePathError
from .request_handler import EXTENSIONS_ONLY, RequestContext, RequestRefused

log = Logger.get("EXT.USES")

# section → the info key the extension declares those uses under
_DECLARED = {"ai": "uses", "voice": "voice_uses"}


async def _set_use(section: str, params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    name = await _caller_name(ctx)
    use = params.get("use")
    profile = params.get("profile")
    if not isinstance(use, str) or not use.strip():
        raise RequestRefused(AI_ERROR_INVALID, "use is required (one of the extension's declared uses).")
    if profile is not None and not isinstance(profile, str):
        raise RequestRefused(AI_ERROR_INVALID, "profile must be a profile id, or null to clear the pick.")
    use_id, pid = use.strip(), (profile or "").strip() or None
    paired = await asyncio.to_thread(get_paired_extension, ctx.workspace_path, ctx.msg.routing.sender_id)
    declared = {u["id"] for u in declared_uses(paired.info if paired else {}, _DECLARED[section])}
    if use_id not in declared:
        raise RequestRefused(AI_ERROR_INVALID, f"{use_id!r} isn't one of this extension's declared {section} uses.")
    key = f"{name}:{use_id}"
    try:
        await asyncio.to_thread(ctx.server_ctx.preferences.update_many, {f"{section}.uses.{key}": pid})
    except (ValidationError, PreferencePathError, ValueError) as exc:
        message = str(exc).splitlines()[-1] if isinstance(exc, ValidationError) else str(exc)
        raise RequestRefused(AI_ERROR_INVALID, f"Not saved: {message}") from exc
    log.info(f"✅ {section} use picked by {name} — {key} · {pid or 'no profile'}")
    return {"use": use_id, "profile": pid}


async def handle_ai_uses_set(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    return await _set_use("ai", params, ctx)


async def handle_voice_uses_set(params: dict[str, Any], ctx: RequestContext) -> dict[str, Any]:
    return await _set_use("voice", params, ctx)


USES_REQUEST_HANDLERS: tuple[tuple[str, Any, frozenset[str]], ...] = (
    (METHOD_AI_USES_SET, handle_ai_uses_set, EXTENSIONS_ONLY),
    (METHOD_VOICE_USES_SET, handle_voice_uses_set, EXTENSIONS_ONLY),
)
