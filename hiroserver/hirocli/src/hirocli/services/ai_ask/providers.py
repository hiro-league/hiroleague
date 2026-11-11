"""Answering one question on one profile's model — the provider seam of the AI ask.

Two kinds of provider answer an ask:

- ``ChatModelProvider`` — API and local models, through the core's own model layer
  (``model_factory.build_chat_model_from_tuning`` with the profile's tuning, which already handles
  each provider's thinking/temperature quirks). Pictures go as image content parts, a sound clip as
  an audio part (Gemini), and the answer is held to the JSON schema by structured output (JSON mode
  where the provider needs it, with the schema written into the question). Tokens come from the
  reply's usage metadata, the cost from the catalog pricing.
- a **plan tool** (``claude_code`` / ``codex``): looked up by provider id in a registry
  (``register_plan_tool``) and called with ``PlanCall`` (prompt, pictures, schema, thinking, timeout,
  wait, plus the workspace, its line and ``at_once``). services/plans' built-in tools are added the
  first time one is looked up (Part B); a provider id with none fails with "plan tools aren't set up
  yet", and the walk moves on to the profile's fallback.
"""

from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from hiro_commons.log import Logger

from ...domain.credential_store import CredentialStore
from ...domain.model_catalog import get_model_catalog
from ...domain.model_factory import build_chat_model_from_tuning, structured_output_method
from ...domain.preferences import AiProfile, ModelTuning
from .errors import ProviderFailed
from .targets import AskTarget

log = Logger.get("AI.ASK")

# max_tokens when the profile leaves it unset: a JSON answer, and thinking tokens where they
# count as output (ModelTuning's 1024 cuts thinking models off before the answer).
DEFAULT_ASK_MAX_TOKENS = 8192
# How much of a picture the model reads: Gemini's per-part media resolution, OpenAI's image detail
# (low for low and medium — a fixed, small token count — high for high), as HomeHiro's vision.py.
GEMINI_RESOLUTION = {"low": "MEDIA_RESOLUTION_LOW", "medium": "MEDIA_RESOLUTION_MEDIUM", "high": "MEDIA_RESOLUTION_HIGH"}
OPENAI_DETAIL = {"low": "low", "medium": "low", "high": "high"}
# A ```json … ``` block around a reply asked for JSON alone (HomeHiro saw Gemma 4 do it).
_FENCE_OPEN = re.compile(r"^```(?:json)?", re.IGNORECASE)
_FENCE_CLOSE = re.compile(r"```$")


@dataclass
class ProviderCall:
    """One question to one model."""

    profile: AiProfile
    target: AskTarget
    prompt: str  # with the profile's instructions already added
    pictures: list[bytes] = field(default_factory=list)  # JPEGs, in order
    picture_labels: list[str] = field(default_factory=list)
    sound: bytes | None = None
    sound_mime: str = "audio/wav"
    schema: dict[str, Any] | None = None  # None = a plain text answer
    detail: str = "medium"
    folder: Path | None = None  # a checked folder for a plan tool to read; no other provider can
    timeout: float = 60.0
    wait: bool = True
    workspace_path: Path = Path(".")  # Part B: plan tools keep their login under the workspace
    line: str = ""  # Part B: the plan tool's line ("" = waiting asks; else the app's own)


@dataclass
class ProviderResult:
    text: str  # JSON text when a schema was given
    tokens_in: int
    tokens_out: int
    cost: float | None  # USD; None for local and plan models, or a model without a price
    model: str  # the model that answered, as the provider names it
    estimate: float | None = None  # plan tools: what it would cost on an API key
    # Part B: Codex reports only a total (in and out are 0); None = tokens_in + tokens_out.
    tokens_total: int | None = None


# ---------------------------------------------------------------------------
# Plan tools (Part B plugs in here)
# ---------------------------------------------------------------------------


@dataclass
class PlanCall:
    """What a plan tool is asked with (the contract's seam)."""

    model: str  # as the tool names it (the part after "claude_code:" / "codex:")
    prompt: str
    pictures: list[bytes]
    schema: dict[str, Any] | None
    thinking: str | None
    timeout: float
    wait: bool  # False = an app's line: a busy tool answers busy instead of queueing
    # Part B: where the tool's login lives, whose line the ask waits in ("" = the waiting asks; an
    # app's own id otherwise) and how many of that line may run together (the profile's at_once).
    workspace_path: Path = Path(".")
    line: str = ""
    at_once: int = 1
    folder: Path | None = None  # the tool starts here and may read it (never write): a checked, existing folder


class PlanTool(Protocol):
    async def answer(self, call: PlanCall) -> ProviderResult:
        """Raise ProviderFailed when it can't answer, errors.AskError("busy", …) when busy and not waiting."""
        ...


_PLAN_TOOLS: dict[str, PlanTool] = {}
# Part B: the built-in plan tools (services/plans) are added on the first lookup, so every process that
# asks (the server, the CLI's `hiro ai try`) has them without a startup hook. One registered earlier
# (a test's fake) is kept.
_DEFAULTS_LOADED = False


def register_plan_tool(provider_id: str, tool: PlanTool) -> None:
    """Make ``provider_id`` (``claude_code`` / ``codex``) answer asks."""
    _PLAN_TOOLS[provider_id] = tool


def plan_tool_for(provider_id: str) -> PlanTool | None:
    global _DEFAULTS_LOADED
    if not _DEFAULTS_LOADED:
        _DEFAULTS_LOADED = True
        from ..plans.provider import built_in_plan_tools

        for pid, tool in built_in_plan_tools().items():
            _PLAN_TOOLS.setdefault(pid, tool)
    return _PLAN_TOOLS.get(provider_id)


async def answer_on_plan(call: ProviderCall) -> ProviderResult:
    tool = plan_tool_for(call.target.provider_id)
    if tool is None:
        raise ProviderFailed(f"{call.target.provider_label}: plan tools aren't set up yet")
    if call.sound is not None:
        raise ProviderFailed(f"{call.target.provider_label} can't listen to sound: pick a Gemini profile")
    return await tool.answer(
        PlanCall(
            model=call.target.model_name,
            prompt=call.prompt,
            pictures=list(call.pictures),
            schema=call.schema,
            thinking=call.profile.thinking,
            timeout=call.timeout,
            wait=call.wait,
            workspace_path=call.workspace_path,
            line=call.line,
            at_once=call.profile.at_once,
            folder=call.folder,
        )
    )


# ---------------------------------------------------------------------------
# API and local models
# ---------------------------------------------------------------------------


class ChatModelProvider:
    """API and local models through ``model_factory`` (module notes)."""

    def __init__(self, workspace_path: Path, store: CredentialStore | None) -> None:
        self._workspace_path = workspace_path
        self._store = store

    async def answer(self, call: ProviderCall) -> ProviderResult:
        target = call.target
        if call.folder is not None:
            raise ProviderFailed(f"{target.model_id} can't read a folder: pick a Claude Code or Codex profile")
        if call.pictures and not target.pictures:
            raise ProviderFailed(f"{target.model_id} can't read pictures")
        if call.sound is not None and not target.sound:
            raise ProviderFailed(f"{target.model_id} can't listen to sound: pick a Gemini profile")
        model = self._build(call)
        method = structured_output_method(model)
        prompt = call.prompt
        if call.schema is not None and method == "json_mode":
            # JSON mode keeps the answer JSON but never sees the schema: say it in the question.
            prompt = f"{prompt}\n\nAnswer with JSON only, matching this JSON schema:\n{json.dumps(call.schema)}"
        from langchain_core.messages import HumanMessage

        message = HumanMessage(content=_content(call, prompt))
        try:
            if call.schema is None:
                raw = await model.ainvoke([message])
                parsed: Any = None
            else:
                runnable = model.with_structured_output(
                    _titled(call.schema), include_raw=True, **({"method": method} if method else {})
                )
                out = await runnable.ainvoke([message])
                raw, parsed = out.get("raw"), out.get("parsed")
        except ProviderFailed:
            raise
        except Exception as exc:  # the provider's own error (key, quota, 4xx/5xx, connection)
            raise ProviderFailed(f"{target.provider_label}: {type(exc).__name__}: {str(exc)[:300]}") from exc
        tokens_in, tokens_out, cached = _usage(raw)
        text = _answer_text(raw, parsed, call.schema is not None, target)
        cost = self._cost(target, tokens_in, tokens_out, cached)
        return ProviderResult(text=text, tokens_in=tokens_in, tokens_out=tokens_out, cost=cost, model=target.model_name)

    def _build(self, call: ProviderCall) -> Any:
        profile = call.profile
        defaults = ModelTuning()
        tuning = ModelTuning(
            temperature=profile.temperature if profile.temperature is not None else defaults.temperature,
            max_tokens=profile.max_tokens or DEFAULT_ASK_MAX_TOKENS,
            thinking=profile.thinking,
            num_ctx=profile.num_ctx if call.target.kind == "local" else None,
        )
        try:
            return build_chat_model_from_tuning(
                call.target.model_id,
                workspace_path=self._workspace_path,
                tuning=tuning,
                credential_store=self._store,
                spec=call.target.spec,
            )
        except ValueError as exc:  # no key / no endpoint / unsupported provider
            raise ProviderFailed(str(exc)) from exc

    @staticmethod
    def _cost(target: AskTarget, tokens_in: int, tokens_out: int, cached: int) -> float | None:
        if target.kind != "api":
            return None  # a home PC: free
        estimate = get_model_catalog().estimate_token_usage_cost(
            model_id=target.model_id,
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            cached_input_tokens=cached,
        )
        return estimate.estimated_total if estimate.pricing_available else None


def _content(call: ProviderCall, prompt: str) -> list[dict[str, Any]]:
    """Pictures first (each after its label, if any), then the sound, then the words."""
    parts: list[dict[str, Any]] = []
    for i, jpeg in enumerate(call.pictures):
        label = call.picture_labels[i] if i < len(call.picture_labels) else ""
        if label:
            parts.append({"type": "text", "text": label})
        parts.append(_image_part(call.target.provider_id, base64.b64encode(jpeg).decode("ascii"), call.detail))
    if call.sound is not None:
        parts.append({"type": "audio", "base64": base64.b64encode(call.sound).decode("ascii"), "mime_type": call.sound_mime})
    parts.append({"type": "text", "text": prompt})
    return parts


def _image_part(provider_id: str, b64: str, detail: str) -> dict[str, Any]:
    if provider_id == "google":
        return {
            "type": "image",
            "base64": b64,
            "mime_type": "image/jpeg",
            "media_resolution": GEMINI_RESOLUTION.get(detail, GEMINI_RESOLUTION["medium"]),
        }
    url = f"data:image/jpeg;base64,{b64}"
    if provider_id == "openai":
        return {"type": "image_url", "image_url": {"url": url, "detail": OPENAI_DETAIL.get(detail, "low")}}
    return {"type": "image_url", "image_url": {"url": url}}


def _titled(schema: dict[str, Any]) -> dict[str, Any]:
    # Function calling / json_schema name the schema by its title; an extension's schema may have none.
    return schema if schema.get("title") else {**schema, "title": "answer"}


def _usage(raw: Any) -> tuple[int, int, int]:
    """(tokens in, tokens out, cached tokens in) from the reply's usage metadata."""
    from ...runtime.agent_graph.graph_kit import usage_from_metadata

    meta = getattr(raw, "usage_metadata", None) or {}
    usage = usage_from_metadata(dict(meta))
    return usage.get("input_tokens", 0), usage.get("output_tokens", 0), usage.get("cached_input_tokens", 0)


def _answer_text(raw: Any, parsed: Any, want_json: bool, target: AskTarget) -> str:
    if want_json and parsed is not None:
        return parsed if isinstance(parsed, str) else json.dumps(parsed, ensure_ascii=False)
    text = _message_text(raw)
    if not want_json:
        if not text:
            raise ProviderFailed(f"{target.model_id} gave no answer")
        return text
    # Structured output didn't parse (e.g. a fenced block): read the JSON from the text ourselves.
    cleaned = _FENCE_CLOSE.sub("", _FENCE_OPEN.sub("", text.strip())).strip()
    try:
        return json.dumps(json.loads(cleaned), ensure_ascii=False)
    except ValueError as exc:
        hint = cleaned[:200] if cleaned else "no text"
        raise ProviderFailed(f"{target.model_id} didn't answer in JSON ({hint})") from exc


def _message_text(raw: Any) -> str:
    content = getattr(raw, "content", None)
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        texts = [
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict) and part.get("type") in ("text", None) and part.get("text")
        ]
        texts += [part for part in content if isinstance(part, str)]
        return "".join(texts).strip()
    return ""


def elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
