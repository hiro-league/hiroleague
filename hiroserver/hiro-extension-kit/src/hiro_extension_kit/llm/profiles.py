"""Asking an AI: since Phase 7a every question the app asks goes to the HiroLeague core (`ai.ask`), which answers it
with its AI profiles (the model, thinking, budget, fallbacks; its admin's Catalog → AI profiles and Uses).

A task names a profile of its own (one of the core's: core_ai.py lists them), or none, and the
core takes the profile its Uses page gives the task's use (`<extension>:<use>`, declared in the app's Extension.uses). `ask()`:
- sends the words, the pictures (base64 JPEGs, with their labels from the LLM requests log), the sound (base64, with
  its type), the answer's schema and, for an app's question, `wait` false (the core answers `busy` at a plan tool that
  is already busy, and the app sends it again, instead of queueing behind the app's own);
- maps the core's answer to `Asked` and adds what the core tried to the LLM requests log (recorder.py), so Logs →
  LLM requests and LLM usage keep working from the answers;
- maps the core's refusals to the errors callers handle: `LimitReached` (429) when every profile in the chain is over
  its budget (a copy waits, then asks again), `Busy` (409) for an app's question at a busy tool, `Unavailable` (503)
  when the app isn't connected to the core or no profile is set for the use, `LLMError` (502) when the core tried
  and every profile failed (its message says why) or didn't answer in time.
"""

import base64
import time
from dataclasses import dataclass, field
from typing import Any

from hiro_channel_sdk import ExtensionRequestError

from .. import identity
from .. import calls
from ..errors import Busy, AppError, Unavailable
from ..hiroleague import link
from ..extension import ext
from . import Detail, LLMError, core_ai, recorder

log = identity.logger("llm")

AI_ASK = "ai.ask"  # the core's request (extensions only)
def _use_names() -> dict[str, str]:
    """The kinds of use that ask an AI, as declared to the core (Extension.uses): id → name."""
    return {u.id: u.name for u in ext().uses}
ASK_TIMEOUT = 300.0  # seconds the core may take when the asker gives no limit (a fallback, a plan tool starting a program)
SLACK = 15.0  # seconds more than the asker's own limit: the core's fallbacks and its own answer on top
WHERE = "HiroLeague's admin (Catalog → Uses)"
PLAN_PROVIDERS = ("claude_code", "codex")  # the core's plan tools (catalog hosting "plan")
LOCAL_PROVIDERS = ("lm_studio", "ollama")


class LimitReached(AppError):
    """Every profile that could answer has reached its limit (429): the question waits."""

    status = 429


@dataclass
class Asked:
    """An answer, and which profile gave it."""

    text: str
    tokens: int
    tokens_in: int
    tokens_out: int
    ms: int
    cost: float | None  # USD; None on a plan or a local server
    provider: str
    model: str
    profile_id: str
    profile_name: str
    plan: bool  # asked on the owner's plan: no cost
    notes: list[str] = field(default_factory=list)  # the profiles passed over, and why
    estimate: float | None = None  # USD on a plan: what it would cost on an API key


def _billing(provider: str, plan: bool = False) -> str:
    """Who pays for a try, as the LLM usage page counts it: "api", "plan" or "local"."""
    if plan or provider in PLAN_PROVIDERS:
        return "plan"
    return "local" if provider in LOCAL_PROVIDERS or provider.startswith("local") else "api"


def _int(v: Any) -> int:
    return int(v) if isinstance(v, int | float) and not isinstance(v, bool) else 0


def _money(v: Any) -> float | None:
    return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None


def asked(answer: Any) -> Asked:
    """The core's answer as the app's `Asked` (pure). LLMError when it has no text."""
    if not isinstance(answer, dict) or not isinstance(answer.get("text"), str):
        raise LLMError("HiroLeague's answer has no text the app can read")
    tokens_in, tokens_out = _int(answer.get("tokens_in")), _int(answer.get("tokens_out"))
    return Asked(text=answer["text"], tokens=_int(answer.get("tokens")) or tokens_in + tokens_out, tokens_in=tokens_in,
                 tokens_out=tokens_out, ms=_int(answer.get("ms")), cost=_money(answer.get("cost")),
                 provider=str(answer.get("provider") or ""), model=str(answer.get("model") or ""),
                 profile_id=str(answer.get("profile_id") or ""),
                 profile_name=str(answer.get("profile_name") or answer.get("profile_id") or ""),
                 plan=bool(answer.get("plan")), notes=[str(n) for n in answer.get("notes") or []],
                 estimate=_money(answer.get("estimate")))


def _record(a: Asked, tries: Any, prompt: str, pictures: list[bytes], schema: dict, detail: Detail) -> None:
    """What the core tried, in the current LLM requests log entry: each profile passed over as a note, each model
    asked as a try (the one that answered with the answer's tokens, time and cost)."""
    for note in a.notes:
        recorder.passed_over(note)
    rows = [t for t in tries if isinstance(t, dict)] if isinstance(tries, list) else []
    asked_rows = [t for t in rows if t.get("status") in ("ok", "failed")]
    if not any(t.get("status") == "ok" for t in asked_rows):  # the core sent no tries: the answer as one
        asked_rows.append({"profile_id": a.profile_id, "provider": a.provider, "model": a.model, "status": "ok", "ms": a.ms})
    for t in asked_rows:
        provider, model = str(t.get("provider") or a.provider), str(t.get("model") or a.model)
        pid = str(t.get("profile_id") or "")
        name = a.profile_name if pid == a.profile_id else core_ai.name_of(pid) or pid or None
        tr = recorder.trying(provider, model, prompt, pictures, schema, detail if pictures else None, None,
                             billing=_billing(provider, a.plan and t.get("status") == "ok"), profile=name)
        if t.get("status") == "ok":
            tr.answered(a.text, a.tokens_in, a.tokens_out, _int(t.get("ms")) or a.ms, a.cost)
            tr.estimate = a.estimate
        else:
            tr.failed(Exception(str(t.get("error") or "failed")), _int(t.get("ms")))


def _refused(exc: ExtensionRequestError, use: str, timeout: float) -> AppError:
    """The core's error as the one callers handle (the module's notes)."""
    code, said = exc.code, exc.message
    if code == "not_connected":
        return Unavailable(f"Not asked: {core_ai._no_core()}")
    if code == "timeout":
        return LLMError(f"HiroLeague didn't answer in {timeout:.0f} s")
    if code == "no_profile":
        return Unavailable(f"No AI profile for {_use_names().get(use, use)}: set one in {WHERE}.")
    if code == "budget":
        return LimitReached(f"Not asked: {said}")
    if code == "busy":
        return Busy(said)
    if code == "failed":
        return LLMError(said)
    if code in ("invalid", "invalid_params"):
        return LLMError(f"HiroLeague refused the question: {said}", 400)
    return LLMError(f"HiroLeague failed ({code}): {said}")


async def ask(profile_id: str | None, use: str, prompt: str, pictures: list[bytes], schema: dict,
              detail: Detail = "medium", local_only: bool = False, timeout: float | None = None, line: str = "",
              sound: bytes | None = None) -> Asked:
    """One question, asked of the HiroLeague core (see the module's notes), about `pictures` (JPEGs, in order; none:
    words only). `profile_id`: one of the core's profiles; None: the core's profile for `use`. `local_only`: the
    picture may only go to a model on the home's own machines (a camera's privacy, vision/): the core passes over
    every profile that isn't local. `timeout`: seconds the model may take (a question with many pages to read); none:
    the core's own limit. `line`: "" for the app's own questions (they wait their turn at a busy plan tool), else the
    id of the app that asks (answered `Busy` instead: apps_api.py). `sound`: a WAV heard with the words (the Wake
    word's check)."""
    if not link.client.connected:  # checked first: nothing was asked, nothing to log
        raise Unavailable(f"Not asked: {core_ai._no_core()}")
    if recorder.active():
        return await _ask(profile_id, use, prompt, pictures, schema, detail, local_only, timeout, line, sound)
    async with recorder.recording("Other", "Asked without a label"):  # kept in Logs → LLM requests all the same
        return await _ask(profile_id, use, prompt, pictures, schema, detail, local_only, timeout, line, sound)


async def _ask(profile_id: str | None, use: str, prompt: str, pictures: list[bytes], schema: dict, detail: Detail,
               local_only: bool, timeout: float | None, line: str, sound: bytes | None) -> Asked:
    labels = recorder.labels()
    params: dict[str, Any] = {
        "use": use, "prompt": prompt, "schema": schema, "detail": detail, "local_only": local_only, "wait": not line,
        **({"profile": await core_ai.resolved(profile_id)} if profile_id else {}),
        **({"pictures": [base64.b64encode(p).decode() for p in pictures],
            "picture_labels": [labels[i] if i < len(labels) else f"Picture {i + 1}" for i in range(len(pictures))]}
           if pictures else {}),
        **({"sound": {"b64": base64.b64encode(sound).decode(), "mime": "audio/wav"}} if sound else {}),
        **({"timeout": timeout} if timeout else {}),
        # Phase 7b: the core's AI usage files the ask under this label (the camera, or the task).
        **({"label": label} if (label := recorder.usage_label()) else {}),
    }
    wait = (timeout or ASK_TIMEOUT) + SLACK
    started, clock = calls.start(), time.monotonic()
    try:
        answer = await link.client.request(AI_ASK, params, timeout=wait)
    except ExtensionRequestError as exc:
        error = _refused(exc, use, wait)
        if isinstance(error, LLMError):  # the core tried (or may have): kept in the requests log as a failed try
            t = recorder.trying("HiroLeague", "", prompt, pictures, schema, detail if pictures else None, None, billing="api")
            t.failed(error, int((time.monotonic() - clock) * 1000))
        raise error from exc
    calls.done(log, f"HiroLeague: {AI_ASK} ({_use_names().get(use, use)})", started, timeout=wait, paid=True)
    a = asked(answer)
    _record(a, answer.get("tries"), prompt, pictures, schema, detail)
    return a


def exists(profile_id: str) -> bool:
    """For settings checks outside a request (a copy's profile still one of the core's?)."""
    return core_ai.exists(profile_id)
