"""Running an ask: profile → its fallbacks, within each profile's limits (Phase 7a contract §4).

``AskRunner.ask``:

- picks the profile: the one given (a copy's own pick), else ``ai.uses["<extension>:<use>"]``;
  neither → ``no_profile``;
- walks profile → fallback → … (at most AI_MAX_FALLBACKS after the first, never a loop) and moves
  on when a profile is over its limit (``max_cost_day`` for API models, ``max_per_hour`` for plan
  and local models), its provider fails or times out, it can't take what was sent (pictures,
  sound), or ``local_only`` rules it out (a camera's pictures may stay in the home);
- a plan profile already answering ``at_once`` asks, with ``wait`` false (an app's line), answers
  ``busy`` at once — never passed to the fallback (a busy plan must not turn into paid calls);
- runs at most ``at_once`` asks per profile together (an in-process semaphore), and one ask at a
  time per local server (they share the PC's GPU);
- counts every ask in the core's AI usage (Phase 7b, ``ai_usage``): an answered one for the profile
  that answered (``ok``, or ``fell back`` when an earlier profile was passed over), an unanswered one
  as ``failed`` for the use's profile; with the person and label the asker sent. Busy and Try it on a
  draft aren't counted.

With nothing left it raises ``AskError``: ``budget`` when limits stopped every profile and none
failed, else ``failed`` with what each one said. The answer mirrors HomeHiro's ``Asked`` (plus
``estimate`` and ``tries``) so HomeHiro's log keeps recording from it.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from hiro_channel_sdk.constants import (
    AI_ERROR_BUDGET,
    AI_ERROR_BUSY,
    AI_ERROR_FAILED,
    AI_ERROR_INVALID,
    AI_ERROR_NO_PROFILE,
)
from hiro_commons.log import Logger

from ...domain.credential_store import CredentialStore
from ...domain.preferences import AI_MAX_FALLBACKS, AiProfile, LocalServerSettings, WorkspacePreferences
from ...domain.workspace import workspace_id_for_path
from ..ai_usage import HIRO_SOURCE, UsageCall, profile_usage, record_async
from . import local_servers, usage
from .errors import AskError, ProviderFailed
from .providers import ChatModelProvider, ProviderCall, ProviderResult, answer_on_plan, elapsed_ms
from .targets import AskTarget, resolve_target

log = Logger.get("AI.ASK")

# Seconds one model may take when the ask doesn't say (HomeHiro's limits).
DEFAULT_TIMEOUT_S = {"api": 60.0, "local": 180.0, "plan": 120.0}
MAX_TIMEOUT_S = 1800.0
DETAILS = ("low", "medium", "high")
# Profile id used by Try it for a profile that isn't saved yet (never counted).
DRAFT_PROFILE_ID = "__draft__"


@dataclass
class AskRequest:
    prompt: str
    use: str | None = None  # "<extension>:<use id>"; None for Try it
    profile_id: str | None = None
    pictures: list[bytes] = field(default_factory=list)
    picture_labels: list[str] = field(default_factory=list)
    sound: bytes | None = None
    sound_mime: str = "audio/wav"
    schema: dict[str, Any] | None = None
    detail: str = "medium"
    local_only: bool = False
    timeout: float | None = None
    wait: bool = True
    who: str = ""  # who asks, for the log ("home", "admin")
    # Phase 7b: what AI usage files the ask under — the person it is for (a person id) and a free label.
    person_id: str = ""
    label: str = ""

    @property
    def source(self) -> str:
        """The extension that asks (``home`` of ``home:ask``); the core itself for Try it."""
        return self.use.partition(":")[0] if self.use else HIRO_SOURCE

    @property
    def use_id(self) -> str:
        return self.use.partition(":")[2] if self.use else "try_it"


@dataclass
class AskAnswer:
    text: str
    profile_id: str
    profile_name: str
    provider: str
    model: str
    plan: bool
    ms: int
    tokens: int
    tokens_in: int
    tokens_out: int
    cost: float | None
    estimate: float | None
    notes: list[str]
    tries: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class _Walk:
    notes: list[str] = field(default_factory=list)
    tries: list[dict[str, Any]] = field(default_factory=list)
    limited: bool = False
    failed: bool = False

    def skip(self, pid: str, target: AskTarget | None, why: str, *, label: str) -> None:
        self.notes.append(f"{label}: {why}")
        self.tries.append(_try(pid, target, "skipped", why, 0))

    def fail(self, pid: str, target: AskTarget | None, why: str, ms: int, *, label: str) -> None:
        self.failed = True
        self.notes.append(f"{label}: {why}")
        self.tries.append(_try(pid, target, "failed", why, ms))


def _try(pid: str, target: AskTarget | None, status: str, error: str | None, ms: int) -> dict[str, Any]:
    out: dict[str, Any] = {
        "profile_id": pid,
        "provider": target.provider_id if target else "",
        "model": target.model_name if target else "",
        "billing": target.kind if target else "",  # Phase 7b: an unanswered ask is counted under its first try's payer
        "status": status,
        "ms": ms,
    }
    if error:
        out["error"] = error
    return out


class AskRunner:
    """One per workspace and event loop (``get_ask_runner``): it owns the semaphores."""

    def __init__(self, workspace_path: Path) -> None:
        self._workspace_path = workspace_path
        self._profile_slots: dict[tuple[str, int], asyncio.Semaphore] = {}
        self._server_locks: dict[str, asyncio.Lock] = {}

    @property
    def workspace_path(self) -> Path:
        return self._workspace_path

    async def ask(
        self,
        request: AskRequest,
        *,
        prefs: WorkspacePreferences,
        draft: AiProfile | None = None,
    ) -> AskAnswer:
        """Answer ``request`` (module notes). ``draft``: Try it on a profile not saved yet."""
        _check_request(request)
        profiles = dict(prefs.ai.profiles)
        if draft is not None:
            profiles[DRAFT_PROFILE_ID] = draft
            pid: str | None = DRAFT_PROFILE_ID
        else:
            pid = (request.profile_id or "").strip() or (prefs.ai.uses.get(request.use) if request.use else None)
        if not pid:
            what = f"the use {request.use!r}" if request.use else "this ask"
            raise AskError(AI_ERROR_NO_PROFILE, f"No AI profile for {what}: pick one on the Catalog's Uses tab.")
        if pid not in profiles:
            raise AskError(AI_ERROR_NO_PROFILE, f"There's no AI profile {pid!r}.")

        store = _credential_store(self._workspace_path)
        walk = _Walk()
        seen: list[str] = []
        current: str | None = pid
        while current and current not in seen and len(seen) <= AI_MAX_FALLBACKS:
            seen.append(current)
            profile = profiles.get(current)
            if profile is None:
                walk.skip(current, None, "a profile that no longer exists", label=current)
                break
            answer = await self._ask_profile(request, current, profile, store, walk, prefs.ai.local_servers)
            if answer is not None:
                return answer
            current = profile.fallback

        message = "Not asked: " + ("; ".join(walk.notes) or "no profile could answer")
        code = AI_ERROR_BUDGET if walk.limited and not walk.failed else AI_ERROR_FAILED
        if pid != DRAFT_PROFILE_ID:
            first = walk.tries[0] if walk.tries else {}
            failed = _usage_call(
                request, pid, profiles[pid], first.get("provider", ""), first.get("model", ""), first.get("billing", ""), "failed"
            )
            # The time every profile tried took (as HomeHiro's usage counted it).
            await record_async(self._workspace_path, replace(failed, ms=_tries_ms(walk)))
        log.warning(
            f"⚠️ AI ask not answered — {request.who or 'someone'} · {request.use or pid} · {code}",
            notes=walk.notes,
        )
        raise AskError(code, message, notes=walk.notes, tries=walk.tries)

    async def _ask_profile(
        self,
        request: AskRequest,
        pid: str,
        profile: AiProfile,
        store: CredentialStore | None,
        walk: _Walk,
        local_settings: dict[str, LocalServerSettings],
    ) -> AskAnswer | None:
        """This profile's answer, or None after noting why the walk moves on."""
        label = profile.label
        try:
            target = resolve_target(self._workspace_path, profile.model, store=store)
        except ValueError as exc:
            walk.fail(pid, None, str(exc), 0, label=label)
            return None
        if request.local_only and target.kind != "local":
            walk.skip(pid, target, "not a local model, and this ask allows local models only", label=label)
            return None
        if target.not_ready:
            walk.fail(pid, target, target.not_ready, 0, label=label)
            return None
        if pid != DRAFT_PROFILE_ID:
            try:
                seen_usage = await asyncio.to_thread(profile_usage, self._workspace_path, pid)
            except Exception as exc:  # a limit we can't read must not stop the ask; it's logged
                log.error(f"❌ AI usage unreadable — {label}", error=str(exc), exc_info=True)
                seen_usage = None
            why = usage.why_limited(profile, target.kind, seen_usage) if seen_usage is not None else None
            if why:
                walk.limited = True
                walk.skip(pid, target, why, label=label)
                return None

        question = f"{request.prompt}\n\n{profile.instructions.strip()}" if profile.instructions.strip() else request.prompt
        timeout = min(request.timeout or DEFAULT_TIMEOUT_S[target.kind], MAX_TIMEOUT_S)
        call = ProviderCall(
            profile=profile,
            target=target,
            prompt=question,
            pictures=request.pictures,
            picture_labels=request.picture_labels,
            sound=request.sound,
            sound_mime=request.sound_mime,
            schema=request.schema,
            detail=request.detail,
            timeout=timeout,
            wait=request.wait,
            workspace_path=self._workspace_path,
            # Part B: a plan tool's line — the waiting asks share one; an app (wait false) has its own.
            line="" if request.wait else (request.use or request.who or "app"),
        )
        started = time.monotonic()
        try:
            if target.kind == "plan":
                # Part B: the plan tool's own line runs at_once per line and answers busy itself; its run has
                # the timeout (cli.run), so waiting in line doesn't spend it (HomeHiro's rule).
                result = await self._answer(call, store, local_settings)
            else:
                async with self._slot(pid, profile.at_once):
                    result = await asyncio.wait_for(self._answer(call, store, local_settings), timeout=timeout)
        except asyncio.TimeoutError:
            walk.fail(pid, target, f"no answer within {timeout:.0f} s", elapsed_ms(started), label=label)
            log.warning(f"⚠️ AI ask timed out — {label} · {target.model_id}", elapsed_ms=elapsed_ms(started))
            return None
        except ProviderFailed as exc:
            walk.fail(pid, target, str(exc), elapsed_ms(started), label=label)
            log.warning(f"⚠️ AI ask failed — {label} · {target.model_id}", error=str(exc), elapsed_ms=elapsed_ms(started))
            return None
        except AskError as exc:
            if exc.code != AI_ERROR_BUSY:
                raise
            # Busy is never a move-on (a busy plan must not turn into paid calls): answer busy with the walk so far.
            raise AskError(AI_ERROR_BUSY, exc.message, notes=walk.notes, tries=walk.tries) from exc
        ms = elapsed_ms(started)
        if pid != DRAFT_PROFILE_ID:
            # Answered after passing over earlier profiles = "fell back" (record_async never raises).
            call = _usage_call(
                request, pid, profile, target.provider_id, result.model or target.model_name, target.kind,
                "fell back" if walk.tries else "ok",
            )
            await record_async(
                self._workspace_path,
                replace(
                    call,
                    tokens_in=result.tokens_in,
                    tokens_out=result.tokens_out,
                    # Its own time plus the profiles passed over before it (as HomeHiro's usage counted it).
                    ms=ms + _tries_ms(walk),
                    cost=result.cost or 0.0,
                    estimate=result.estimate or 0.0,
                    # Answered at $0 for want of a price (an API model without one, a plan without an estimate).
                    unpriced=_unpriced(target.kind, result.cost, result.estimate),
                ),
            )
        walk.tries.append(_try(pid, target, "ok", None, ms))
        log.info(
            f"✅ AI ask answered — {request.who or 'someone'} · {request.use or 'try'} · {label}",
            model=target.model_id,
            elapsed_ms=ms,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            cost=result.cost,
            passed_over=len(walk.notes),
        )
        return AskAnswer(
            text=result.text,
            profile_id=pid,
            profile_name=label,
            provider=target.provider_id,
            model=result.model,
            plan=target.kind == "plan",
            ms=ms,
            tokens=result.tokens_total if result.tokens_total is not None else result.tokens_in + result.tokens_out,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            cost=result.cost,
            estimate=result.estimate,
            notes=walk.notes,
            tries=walk.tries,
        )

    async def _answer(
        self, call: ProviderCall, store: CredentialStore | None, local_settings: dict[str, LocalServerSettings]
    ) -> ProviderResult:
        if call.target.kind == "plan":
            return await answer_on_plan(call)
        provider = ChatModelProvider(self._workspace_path, store)
        if call.target.kind != "local":
            return await provider.answer(call)
        # One ask at a time per local server: they share the home PC's GPU.
        pid, model = call.target.provider_id, call.target.model_name
        lock = self._server_locks.setdefault(pid, asyncio.Lock())
        async with lock:
            # Part B: make room and load the model with the server's settings first (local_servers.py).
            settings = local_settings.get(pid) or LocalServerSettings()
            await local_servers.prepare(
                self._workspace_path, pid, model, settings, context=call.profile.num_ctx, store=store
            )
            try:
                return await provider.answer(call)
            finally:
                local_servers.asked(self._workspace_path, pid, model)

    async def unload_idle(self, local_settings: dict[str, LocalServerSettings]) -> list[str]:
        """Unload what the core loaded on local servers once idle (the AI background job, every minute)."""
        return await local_servers.run_unload_idle(
            self._workspace_path, local_settings, self._server_locks, _credential_store(self._workspace_path)
        )

    def _slot(self, pid: str, at_once: int) -> asyncio.Semaphore:
        # Keyed with at_once, so a changed limit takes effect on the next ask.
        key = (pid, at_once)
        slot = self._profile_slots.get(key)
        if slot is None:
            slot = self._profile_slots[key] = asyncio.Semaphore(at_once)
        return slot


def _tries_ms(walk: _Walk) -> int:
    return sum(int(t.get("ms") or 0) for t in walk.tries)


def _unpriced(billing: str, cost: float | None, estimate: float | None) -> int:
    """1 when an answer went without a price: an API model with no cost, a plan with no estimate (local is free)."""
    if billing == "api":
        return int(cost is None)
    if billing == "plan":
        return int(estimate is None)
    return 0


def _usage_call(
    request: AskRequest, pid: str, profile: AiProfile, provider: str, model: str, billing: str, result: str
) -> UsageCall:
    return UsageCall(
        kind="question",
        source=request.source,
        use=request.use_id,
        profile_id=pid,
        profile_name=profile.label,
        provider=provider,
        model=model,
        billing=billing if billing in ("api", "plan", "local") else "api",
        person_id=request.person_id,
        label=request.label,
        result=result,
    )


def _check_request(request: AskRequest) -> None:
    if not request.prompt.strip():
        raise AskError(AI_ERROR_INVALID, "The ask has no prompt.")
    if request.detail not in DETAILS:
        raise AskError(AI_ERROR_INVALID, f"detail must be one of {', '.join(DETAILS)}.")
    if request.schema is not None and not isinstance(request.schema, dict):
        raise AskError(AI_ERROR_INVALID, "schema must be a JSON schema object.")
    if request.timeout is not None and request.timeout <= 0:
        raise AskError(AI_ERROR_INVALID, "timeout must be more than 0 seconds.")


def _credential_store(workspace_path: Path) -> CredentialStore | None:
    wid = workspace_id_for_path(workspace_path)
    return CredentialStore(workspace_path, wid) if wid is not None else None


_RUNNERS: dict[str, tuple[asyncio.AbstractEventLoop, AskRunner]] = {}


def get_ask_runner(workspace_path: Path) -> AskRunner:
    """The workspace's runner on the running event loop (semaphores belong to one loop)."""
    loop = asyncio.get_running_loop()
    key = str(workspace_path.resolve())
    held = _RUNNERS.get(key)
    if held is None or held[0] is not loop:
        held = _RUNNERS[key] = (loop, AskRunner(workspace_path))
    return held[1]
