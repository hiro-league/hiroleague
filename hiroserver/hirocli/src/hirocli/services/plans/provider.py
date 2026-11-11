"""Plan tools answering AI asks — plugged in behind ``ai_ask.providers.register_plan_tool`` (ported from
HomeHiro's llm/providers.py ToolProvider / ClaudeCode / Codex and its ``Line``).

Each run starts a program on the owner's plan, so a tool takes its asks in **lines**: the core's own
waiting asks (``wait`` true: an extension's own questions, which take seconds) are one line, and each app
that asks with ``wait`` false (StudyHiro through HomeHiro) has a line of its own, so a camera's question
doesn't wait behind a two-minute homework review, nor it behind the cameras'. A line runs as many at once
as the profile says (``at_once``). Past that, a waiting ask waits its turn, and an app's is answered
``busy`` at once: the app keeps it and sends it again, so it never spends its time limit queueing here (and
a busy plan never turns into paid calls on the fallback).

Each ask gets a fresh folder under ``<workspace>/plans/work/`` holding only its pictures (and Codex's
schema file), removed after. An ask that names a folder (``PlanCall.folder``, a code review) runs the tool
in that folder instead, with look-only tools; the ask's own folder still holds the schema file. The answer's API-price ``estimate`` (what it would have cost on a key) comes
from the catalog price of the model that answered; Codex reports only a token total, so it has none.
"""

from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path

from hiro_channel_sdk.constants import AI_ERROR_BUSY
from hiro_commons.log import Logger

from ...domain.model_catalog import get_model_catalog
from ..ai_ask.errors import AskError, ProviderFailed
from ..ai_ask.providers import PlanCall, ProviderResult
from . import cli, status
from .kinds import PLAN_KINDS, Answered, AnswerUnreadable, PlanKind, picture_names
from .models import CLAUDE_FAMILIES, model_levels

log = Logger.get("PLANS")

# Anthropic bills cached input at a tenth of the input price and writing the cache at 1.25×.
CACHE_READ, CACHE_WRITE = 0.1, 1.25


class Line:
    """The asks of one line at a tool: how many run, and those waiting their turn (first come, first served).
    Lives on the event loop."""

    def __init__(self) -> None:
        self.running = 0
        self._waiting: list[asyncio.Future[None]] = []

    async def enter(self, at_once: int, wait: bool, who: str) -> None:
        """Take a place among the ``at_once`` running, waiting for one when ``wait``, else ``busy`` at once."""
        while self.running >= max(1, at_once):
            if not wait:
                raise AskError(
                    AI_ERROR_BUSY,
                    f"{who} is answering {self.running} of these asks already, as many at once as its profile "
                    f"allows: send it again when one is answered.",
                )
            turn = asyncio.get_running_loop().create_future()
            self._waiting.append(turn)
            try:
                await turn
            finally:
                if turn in self._waiting:
                    self._waiting.remove(turn)
        self.running += 1

    def leave(self) -> None:
        self.running -= 1
        for turn in self._waiting:  # the first still waiting tries again (one cancelled meanwhile is passed over)
            if not turn.done():
                turn.set_result(None)
                break


class PlanToolProvider:
    """One plan tool (``PlanTool`` of the ai_ask seam)."""

    def __init__(self, kind: PlanKind) -> None:
        self.kind = kind
        self._lines: dict[tuple[str, str, int], Line] = {}  # (workspace, line, loop id) → its line

    def _line(self, workspace_path: Path, line: str) -> Line:
        key = (str(workspace_path), line, id(asyncio.get_running_loop()))
        found = self._lines.get(key)
        if found is None:
            found = self._lines[key] = Line()
        return found

    async def answer(self, call: PlanCall) -> ProviderResult:
        turn = self._line(call.workspace_path, call.line)
        await turn.enter(call.at_once, wait=call.wait, who=self.kind.name)
        try:
            effort = self.effort(call.workspace_path, call.model, call.thinking)
            try:
                answered = await asyncio.to_thread(self._answer_now, call, effort)
            except (cli.PlanToolError, AnswerUnreadable) as exc:
                status.recheck(call.workspace_path, self.kind)  # signed out? read again next time
                raise ProviderFailed(str(exc)) from exc
        finally:
            turn.leave()
        return ProviderResult(
            text=answered.text,
            tokens_in=answered.tokens_in,
            tokens_out=answered.tokens_out,
            cost=None,
            model=answered.model,
            estimate=self.estimate(answered),
            tokens_total=answered.tokens_total,
        )

    def _answer_now(self, call: PlanCall, effort: str | None) -> Answered:
        folder = cli.work_folder(call.workspace_path) / uuid.uuid4().hex  # the ask's own: its pictures, nothing else
        folder.mkdir(parents=True)
        try:
            names = picture_names(len(call.pictures)) if call.pictures else []
            for name, jpeg in zip(names, call.pictures, strict=True):
                (folder / name).write_bytes(jpeg)
            if call.folder is not None and (names or not call.folder.is_dir()):
                raise cli.PlanToolError("An ask that reads a folder needs an existing folder and carries no pictures")
            args, stdin = self.kind.question(folder, call.model, effort, call.prompt, names, call.schema, call.folder)
            # With a folder the tool starts in it; its own files (pictures, a schema) stay in the ask's folder.
            r = cli.run(call.workspace_path, self.kind, args, "an AI ask", call.timeout, cwd=call.folder or folder, stdin=stdin)
            return self.kind.answered(r.code, r.out, r.err, call.model, call.schema)
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def effort(self, workspace_path: Path, model: str, thinking: str | None) -> str | None:
        """The profile's thinking level in the tool's words, clamped to what the model takes."""
        if thinking is None:
            return None  # the tool's own default
        if self.kind.id == "claude_code":
            # Claude Code's --effort is low…max; it has no "off": the lowest level is the closest.
            return "low" if thinking in ("off", "minimal") else thinking
        levels = model_levels(workspace_path, self.kind.id, model)
        if not levels:
            return None if thinking == "off" else thinking
        if thinking == "off":
            return "none" if "none" in levels else _lowest(levels)
        from ...domain.model_factory import _clamp_effort  # the catalog clamp the API path uses too

        return _clamp_effort(thinking, set(levels)) or _lowest(levels)

    def estimate(self, answered: Answered) -> float | None:
        """What the ask would have cost on an API key (catalog price of the model that answered)."""
        if not (answered.tokens_in or answered.tokens_out):
            return None  # Codex: a total only
        spec_id = _catalog_id(self.kind.id, answered.model)
        spec = get_model_catalog().get_model(spec_id) if spec_id else None
        price = spec.pricing if spec else None
        if price is None or price.input_per_1m_tokens is None or price.output_per_1m_tokens is None:
            return None
        cached = price.cached_input_per_1m_tokens or price.input_per_1m_tokens * CACHE_READ
        fresh = answered.cache_fresh if (answered.cache_read or answered.cache_written) else answered.tokens_in
        return (
            fresh * price.input_per_1m_tokens
            + answered.cache_read * cached
            + answered.cache_written * price.input_per_1m_tokens * CACHE_WRITE
            + answered.tokens_out * price.output_per_1m_tokens
        ) / 1_000_000


def _lowest(levels: list[str]) -> str:
    order = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
    known = sorted((x for x in levels if x in order and x != "none"), key=order.index)
    return known[0] if known else levels[0]


def _catalog_id(provider_id: str, model: str) -> str | None:
    """The catalog row priced like the plan model: Codex models are OpenAI's; Claude's are Anthropic's
    (a family alias "sonnet" → the catalog's Sonnet; a dated name → the row it starts with)."""
    cat = get_model_catalog()
    if provider_id == "codex":
        return f"openai:{model}" if cat.get_model(f"openai:{model}") else None
    rows = [m.id for m in cat.list_models(provider_id="anthropic", model_kind="chat")]
    exact = f"anthropic:{model}"
    if exact in rows:
        return exact
    for rid in rows:
        if model.startswith(rid.split(":", 1)[1]):
            return rid
    family = next((fid for fid, _, _ in CLAUDE_FAMILIES if fid in model), None)
    return next((rid for rid in rows if family and f"-{family}-" in rid), None)


def built_in_plan_tools() -> dict[str, PlanToolProvider]:
    """claude_code / codex as ai_ask plan tools (added by ``ai_ask.providers.plan_tool_for``)."""
    return {kind.id: PlanToolProvider(kind) for kind in PLAN_KINDS.values()}
