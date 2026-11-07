"""Read what connected extensions know right now (the plan's Phase 5) — Hiro's agent tool.

Each connected extension answers ``extension.state`` with its live state as plain
JSON (HomeHiro: who is home, who is away, which room each person is in). The tool
hands it to Hiro as it is: the core knows nothing about any one extension. Hiro
calls it only when a question needs it, so nothing is read or kept otherwise.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from hiro_channel_sdk import ExtensionRequestError
from hiro_channel_sdk.constants import METHOD_EXTENSION_STATE
from hiro_commons.log import Logger

from .base import Tool, ToolParam

log = Logger.get("EXT_STATE")

_TIMEOUT_S = 15.0


@dataclass
class ExtensionStateResult:
    # One entry per connected extension: {"extension", "description", "state"} or {"extension", "error"}.
    extensions: list[dict[str, Any]] = field(default_factory=list)
    note: str = ""


class ExtensionStateTool(Tool):
    """Ask the connected extensions what they know right now."""

    runtime = True
    surfaces = frozenset({"agent", "http"})
    # Always on: Hiro can read the home even with chat tools switched off (read-only, safe).
    agent_always = True
    # Live: a read from an earlier turn is shown to Hiro as out of date, so it reads again.
    agent_live = True
    name = "extension_state"
    description = (
        "Read what the programs connected to Hiro know right now, live. The home (HomeHiro) "
        "tells who is home, who is away and since when, and which room each person is in and "
        "what they are doing. Use it when asked where someone is, who is home, when someone "
        "came or left, or what is happening at home now. The answer is only true when read: "
        "read it again for every such question, never answer from an earlier read."
    )
    params = {
        "extension": ToolParam(str, "Only this extension (its name, e.g. home); all connected ones when empty", required=False),
    }

    def attach_runtime(self, ctx: Any) -> None:
        # Reason: the extensions are live connections in the running server (ExtensionManager).
        self._runtime = ctx

    def execute(self, **kwargs: Any) -> ExtensionStateResult:
        raise RuntimeError("extension_state is async-only — it needs the running Hiro server")

    async def execute_async(self, extension: str | None = None) -> ExtensionStateResult:
        rt = getattr(self, "_runtime", None)
        if rt is None:
            raise RuntimeError("extension_state has no runtime context — register tools with ToolRegistry(runtime=…).")
        manager = rt.comm_manager.ctx.extension_manager
        if manager is None:
            return ExtensionStateResult(note="Extensions aren't running in this Hiro")
        live = manager.snapshot()
        wanted = (extension or "").strip().lower()
        targets = {eid: s for eid, s in live.items() if not wanted or str(s.get("name") or "").lower() == wanted}
        if not targets:
            note = f"No extension named {extension!r} is connected" if wanted else "No extension is connected now"
            return ExtensionStateResult(note=note)
        started = perf_counter()
        answers = await asyncio.gather(*(self._ask(manager, eid, s) for eid, s in targets.items()))
        log.info(
            f"⬆️ Extension state read — {', '.join(a['extension'] for a in answers)}",
            failed=sum(1 for a in answers if "error" in a),
            elapsed_ms=int((perf_counter() - started) * 1000),
        )
        return ExtensionStateResult(extensions=list(answers))

    @staticmethod
    async def _ask(manager: Any, extension_id: str, live: dict[str, Any]) -> dict[str, Any]:
        info = live.get("info") or {}
        name = str(live.get("name") or extension_id)
        try:
            answer = await manager.request(extension_id, METHOD_EXTENSION_STATE, timeout=_TIMEOUT_S)
        except ExtensionRequestError as exc:
            log.warning(f"⚠️ Extension state not read — {name}", error=exc.message, code=exc.code)
            return {"extension": name, "error": f"{name} didn't answer: {exc.message}"}
        return {"extension": name, "description": str(info.get("description") or ""), "state": answer.get("state")}
