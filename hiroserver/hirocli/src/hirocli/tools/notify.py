"""Notify tool — Hiro tells people something (the plan's Phase 5).

The operation lives in runtime/notify.py; this Tool is its CLI/HTTP face, and the
``notify`` extension request calls the same function. Not offered to the agent by
default (it sends WhatsApp messages to any number given).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from hiro_channel_sdk.constants import NOTIFY_MEDIUM_WHATSAPP, NOTIFY_STYLE_EXACT

from .base import Tool, ToolParam


@dataclass
class NotifyToolResult:
    results: list[dict[str, Any]] = field(default_factory=list)  # {name, number, sent, error?} per person


class NotifyTool(Tool):
    """Tell people something on WhatsApp, as given or in the character's words."""

    runtime = True
    surfaces = frozenset({"agent", "http"})
    agent_default = False
    name = "notify"
    description = (
        "Tell people something on WhatsApp: the text as it is (style exact) or written by "
        "Hiro's character in its own words (style character). Requires the running server."
    )
    params = {
        "to": ToolParam(list, "People to tell: a list of {name, number}, number with the country code"),
        "text": ToolParam(str, "What to tell them"),
        "style": ToolParam(str, "exact (as given, default) or character (the character writes it)", required=False),
        "medium": ToolParam(str, "whatsapp (the only one for now)", required=False),
    }

    def attach_runtime(self, ctx: Any) -> None:
        # Reason: sending needs the running server's channels and agent (runtime/notify.py).
        self._runtime = ctx

    def execute(self, **kwargs: Any) -> NotifyToolResult:
        raise RuntimeError("notify is async-only — it needs the running Hiro server")

    async def execute_async(
        self,
        to: list[dict[str, Any]],
        text: str,
        style: str | None = None,
        medium: str | None = None,
    ) -> NotifyToolResult:
        from ..runtime.notify import notify, parse_recipients

        rt = getattr(self, "_runtime", None)
        if rt is None:
            raise RuntimeError("notify has no runtime context — register tools with ToolRegistry(runtime=…).")
        results = await notify(
            rt.comm_manager.ctx,
            parse_recipients(to),
            medium=medium or NOTIFY_MEDIUM_WHATSAPP,
            text=text,
            style=style or NOTIFY_STYLE_EXACT,
            asked_by="the admin",
        )
        return NotifyToolResult(results=[asdict(r) for r in results])
