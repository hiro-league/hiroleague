"""The AI asks' background job in the running server (Phase 7a Part B).

Every TICK seconds:

- unloads the local models the core loaded once idle for their server's minutes (local_servers.py);
- tidies plan tool sign-ins (notes how ended ones ended, stops ones not finished in 15 minutes);
- every UPDATE_CHECK_EVERY, runs the plan tools' nightly npm update when it is due (after 4 AM local, once
  a day) in a workspace that uses plan tools (services/plans/updates.py) — a quiet hour, in a thread.

Errors are logged and the loop goes on: it never stops the rest of the core.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from hiro_commons.log import Logger

from ...domain.preferences import AI_PLAN_PROVIDERS
from .runner import get_ask_runner

if TYPE_CHECKING:
    from ...runtime.server_context import ServerContext

log = Logger.get("AI.ASK")

TICK = 60.0  # seconds
UPDATE_CHECK_EVERY = 15 * 60.0
FIRST_UPDATE_CHECK_AFTER = 120.0  # after start: installs soon when a plan profile exists and the tools are missing


async def run_ai_background(ctx: ServerContext) -> None:
    from ..plans.signin import signins
    from ..plans.updates import updater

    next_update_check = time.monotonic() + FIRST_UPDATE_CHECK_AFTER
    try:
        while not ctx.stop_event.is_set():
            try:
                await asyncio.wait_for(ctx.stop_event.wait(), timeout=TICK)
                break
            except asyncio.TimeoutError:
                pass
            prefs = ctx.preferences.current
            try:
                await get_ask_runner(ctx.workspace_path).unload_idle(prefs.ai.local_servers)
            except Exception as exc:
                log.error("❌ Unloading idle local models failed", error=str(exc), exc_info=True)
            try:
                await asyncio.to_thread(signins.tidy)
            except Exception as exc:
                log.error("❌ Tidying plan tool sign-ins failed", error=str(exc), exc_info=True)
            if time.monotonic() >= next_update_check:
                next_update_check = time.monotonic() + UPDATE_CHECK_EVERY
                uses_plans = any(p.model.split(":", 1)[0] in AI_PLAN_PROVIDERS for p in prefs.ai.profiles.values())
                try:
                    if await asyncio.to_thread(updater.nightly_due, ctx.workspace_path, uses_plans=uses_plans):
                        updater.update(ctx.workspace_path, background=True)
                except Exception as exc:
                    log.error("❌ Plan tools nightly update check failed", error=str(exc), exc_info=True)
    finally:
        signins.stop_all()  # a running sign-in's program ends with the server
