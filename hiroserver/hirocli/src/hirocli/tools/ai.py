"""AI profile and use tools (Phase 7a) — what the Catalog's AI tabs, ``hiro ai …`` and HTTP call.

Profiles themselves are created, changed and deleted through the preferences API (``ai.profiles``,
like ``image_profiles``); these tools read them, try one (Try it), and manage which profile each
extension use asks (``ai.uses``):

- ``ai_profiles_list`` — the profiles with kind, provider, limits, today's use, fallback chain, and
  (Phase 7b step 5) Hiro's own jobs: which profile each uses and the model it runs with now;
- ``ai_profile_restore_default`` (Phase 7b step 5) — a job's default profile back to its preset tuning;
- ``ai_try`` — one ask on a saved profile or a draft one (prompt + optional picture), the same run
  as an extension's ``ai.ask`` (fallbacks, limits, counting — a draft is never counted);
- ``ai_uses_list`` / ``ai_uses_set`` / ``ai_uses_forget`` — the declared uses and their picks;
- ``ai_uses_refresh`` — ask connected extensions for their uses again (needs the running server);
- ``local_server_check`` — LM Studio / Ollama: up or down, their models (loaded, loaded by the core) and
  settings; the list is kept so profiles can point at ``lm_studio:<name>`` / ``ollama:<name>``;
- ``local_server_set`` — a server's address and how the core loads its models (idle unload, context, batch);
- ``ai_import_homehiro`` — HomeHiro's LLM profiles, defaults and servers, once (contract section 7);
- ``ai_usage`` (Phase 7b) — every paid AI call per hour over a range, named for the AI usage page;
- ``ai_usage_import_homehiro`` (Phase 7b) — HomeHiro's LLM usage history, once (safe to run again).

The plan tools (Claude Code / Codex) have their own: tools/ai_plans.py.

Preference writes go through the running server's preferences runtime when there is one in this
process (``preferences_runtime_for``), else straight to the file.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hiro_channel_sdk import ExtensionRequestError
from hiro_commons.log import Logger
from pydantic import ValidationError

from ..domain.credential_store import CredentialStore
from ..domain.discovered_models import (
    DISCOVERABLE_LOCAL_PROVIDERS,
    LocalServerError,
    list_discovered_models,
    local_server_url,
    probe_local_models,
    save_discovered_models,
)
from ..domain.preferences import AiProfile
from ..domain.workspace import resolve_workspace
from .base import Tool, ToolParam

log = Logger.get("TOOL.AI")

# Try it's answer shape when no schema is given.
TRY_DEFAULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
}


def _workspace(workspace: str | None) -> tuple[str, Path]:
    entry, _ = resolve_workspace(workspace)
    return entry.id, Path(entry.path)


def _prefs(workspace_path: Path) -> Any:
    from ..runtime.preferences_runtime import preferences_runtime_for

    return preferences_runtime_for(workspace_path).current


def _write_prefs(workspace_path: Path, edits: dict[str, Any]) -> None:
    from ..runtime.preferences_runtime import preferences_runtime_for

    preferences_runtime_for(workspace_path).update_many(edits)


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass
class AiProfilesListResult:
    profiles: list[dict[str, Any]] = field(default_factory=list)
    uses: dict[str, str | None] = field(default_factory=dict)
    # Phase 7b step 5: Hiro's own jobs (services/ai_ask.job_rows).
    jobs: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AiProfileRestoreResult:
    profile_id: str
    preset: str
    profile: dict[str, Any]  # the profile as saved (AI profile fields)


@dataclass
class AiUsageResult:
    rows: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AiTryResult:
    ok: bool
    answer: dict[str, Any] | None = None  # the ai.ask answer shape
    error: dict[str, Any] | None = None  # {code, message, notes, tries}


@dataclass
class AiUsesListResult:
    extensions: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AiUseSetResult:
    key: str
    profile_id: str | None


@dataclass
class AiUseForgetResult:
    key: str
    forgotten: bool


@dataclass
class AiUsesRefreshResult:
    refreshed: list[dict[str, Any]] = field(default_factory=list)  # {extension_id, extension, uses: n}
    failed: list[dict[str, Any]] = field(default_factory=list)  # {extension_id, extension, error}
    note: str = ""


@dataclass
class LocalServerCheckResult:
    provider_id: str
    base_url: str | None
    online: bool
    error: str | None = None
    models: list[dict[str, Any]] = field(default_factory=list)
    # Part B: the admin row/dialog's status and the server's settings.
    state: str = "unknown"  # up | down | no_address
    configured: bool = False
    checked_at: str | None = None
    unload_idle_min: int = 60
    context: int = 16384
    batch: int = 2048


@dataclass
class LocalServerSetResult:
    provider_id: str
    base_url: str | None
    unload_idle_min: int
    context: int
    batch: int


@dataclass
class AiImportResult:
    profiles: dict[str, dict[str, Any]] = field(default_factory=dict)  # hh-<HomeHiro id> -> AI profile fields
    from_ids: dict[str, str] = field(default_factory=dict)
    uses: dict[str, str] = field(default_factory=dict)
    servers: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    written: bool = False
    dry_run: bool = False


@dataclass
class AiUsageImportResult:
    rows: int = 0
    imported: int = 0
    requests: int = 0
    cost: float = 0.0
    first_hour: str | None = None
    last_hour: str | None = None
    cutoff: str | None = None
    notes: list[str] = field(default_factory=list)
    written: bool = False
    dry_run: bool = False


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class AiProfilesListTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "ai_profiles_list"
    description = "List the AI profiles: model, kind (api/local/plan), limits, today's use and fallback chain"
    params = {
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, workspace: str | None = None) -> AiProfilesListResult:
        from ..services.ai_ask import job_rows, profile_rows

        wid, path = _workspace(workspace)
        prefs = _prefs(path)
        store = CredentialStore(path, wid)
        rows = profile_rows(path, prefs, store)
        return AiProfilesListResult(profiles=rows, uses=dict(prefs.ai.uses), jobs=job_rows(path, prefs, store))


class AiProfileRestoreDefaultTool(Tool):
    """Phase 7b step 5: Restore default on a job's default AI profile (``AiProfile.preset``)."""

    surfaces = frozenset({"cli", "http"})
    name = "ai_profile_restore_default"
    description = (
        "Put one of Hiro's job profiles (e.g. hiro-chat) back to its job's preset tuning: thinking, "
        "temperature, max tokens, no context window, no instructions. Its model, limits and fallback stay"
    )
    params = {
        "profile_id": ToolParam(str, "The AI profile id (a job's default profile, e.g. hiro-chat)"),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, profile_id: str, workspace: str | None = None) -> AiProfileRestoreResult:
        from ..domain.preferences.jobs import restore_preset_tuning

        _wid, path = _workspace(workspace)
        pid = profile_id.strip()
        profile = _prefs(path).ai.profiles.get(pid)
        if profile is None:
            raise ValueError(f"No AI profile {pid!r}")
        restored = restore_preset_tuning(profile)  # ValueError when it isn't a job's default
        payload = restored.model_dump(mode="json")
        _write_prefs(path, {f"ai.profiles.{pid}": payload})
        log.info(f"✅ AI profile restored to its default tuning — {restored.label} · {restored.preset}", profile=pid)
        return AiProfileRestoreResult(profile_id=pid, preset=str(restored.preset), profile=payload)


class AiTryTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "ai_try"
    description = (
        "Try an AI profile: ask it one question (optionally about a picture) and show the answer, "
        "with the fallbacks it walked. A saved profile's ask counts toward its limits; a draft's doesn't."
    )
    params = {
        "prompt": ToolParam(str, "The question"),
        "profile_id": ToolParam(str, "A saved AI profile id (or give draft)", required=False),
        "draft": ToolParam(str, "A profile not saved yet, as JSON (AI profile fields)", required=False),
        "picture": ToolParam(str, "A JPEG as base64 (optional)", required=False),
        "schema": ToolParam(str, "JSON schema for the answer, as JSON (default: {answer: string})", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, **kwargs: Any) -> AiTryResult:
        # Sync callers (CLI, worker threads) have no running loop of their own.
        return asyncio.run(self.execute_async(**kwargs))

    async def execute_async(
        self,
        prompt: str,
        profile_id: str | None = None,
        draft: str | dict[str, Any] | None = None,
        picture: str | None = None,
        schema: str | dict[str, Any] | None = None,
        workspace: str | None = None,
    ) -> AiTryResult:
        from ..services.ai_ask import AskError, AskRequest, get_ask_runner
        from ..services.ai_ask.params import decode_b64

        _wid, path = _workspace(workspace)
        try:
            draft_profile = _parse_draft(draft)
            answer_schema = _parse_schema(schema)
            pictures = [decode_b64(picture, "picture")] if picture else []
            if draft_profile is None and not (profile_id or "").strip():
                raise ValueError("Give a profile_id or a draft profile to try.")
        except AskError as exc:
            return AiTryResult(ok=False, error={"code": exc.code, "message": exc.message, "notes": [], "tries": []})
        except ValueError as exc:
            return AiTryResult(ok=False, error={"code": "invalid", "message": str(exc), "notes": [], "tries": []})
        request = AskRequest(
            prompt=prompt,
            profile_id=(profile_id or "").strip() or None,
            pictures=pictures,
            schema=answer_schema,
            who="admin",
        )
        prefs = await asyncio.to_thread(_prefs, path)
        try:
            answer = await get_ask_runner(path).ask(request, prefs=prefs, draft=draft_profile)
        except AskError as exc:
            return AiTryResult(
                ok=False, error={"code": exc.code, "message": exc.message, "notes": exc.notes, "tries": exc.tries}
            )
        return AiTryResult(ok=True, answer=answer.to_dict())


def _parse_draft(draft: str | dict[str, Any] | None) -> AiProfile | None:
    if draft is None or draft == "":
        return None
    try:
        data = json.loads(draft) if isinstance(draft, str) else draft
        return AiProfile.model_validate(data)
    except json.JSONDecodeError as exc:
        raise ValueError(f"draft isn't JSON: {exc}") from exc
    except ValidationError as exc:
        raise ValueError(f"draft isn't a valid AI profile: {exc}") from exc


def _parse_schema(schema: str | dict[str, Any] | None) -> dict[str, Any]:
    if schema is None or schema == "":
        return TRY_DEFAULT_SCHEMA
    try:
        value = json.loads(schema) if isinstance(schema, str) else schema
    except json.JSONDecodeError as exc:
        raise ValueError(f"schema isn't JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("schema must be a JSON schema object")
    return value


class AiUsageTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "ai_usage"
    description = (
        "Every paid AI call the core made (questions, speech, transcription, images, embeddings), per hour, "
        "between two moments: kind, source, use, AI profile, provider, model, who pays, person, label, result, "
        "with calls, tokens, time, cost and estimate"
    )
    params = {
        "start": ToolParam(str, "From (ISO date-time, e.g. 2026-11-02T00:00:00+02:00)"),
        "end": ToolParam(str, "Up to, not including (ISO date-time)"),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, start: str, end: str, workspace: str | None = None) -> AiUsageResult:
        from ..services.ai_usage.view import page_rows

        _wid, path = _workspace(workspace)
        try:
            since, until = _moment(start), _moment(end)
        except ValueError as exc:
            raise ValueError(f"start and end must be ISO date-times: {exc}") from exc
        if until <= since:
            raise ValueError("end must come after start.")
        return AiUsageResult(rows=page_rows(path, _prefs(path), since, until))


def _moment(value: str) -> datetime:
    at = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    # A moment without a zone is the server's local time.
    return at if at.tzinfo else at.astimezone()


class AiUsesListTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "ai_uses_list"
    description = "List each extension's declared AI uses and the profile each one asks (new and removed ones marked)"
    params = {
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, workspace: str | None = None) -> AiUsesListResult:
        from ..services.ai_ask import use_rows

        _wid, path = _workspace(workspace)
        return AiUsesListResult(extensions=use_rows(path, _prefs(path)))


class AiUsesSetTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "ai_uses_set"
    description = "Point an extension use (e.g. home:ask) at an AI profile, or clear its pick"
    params = {
        "key": ToolParam(str, "The use, '<extension>:<use id>' (e.g. home:ask)"),
        "profile_id": ToolParam(str, "The AI profile id; empty to clear the pick", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, key: str, profile_id: str | None = None, workspace: str | None = None) -> AiUseSetResult:
        _wid, path = _workspace(workspace)
        use_key = key.strip()
        pid = (profile_id or "").strip() or None
        # Validated by AiPreferences (key form, profile exists) on write.
        _write_prefs(path, {f"ai.uses.{use_key}": pid})
        log.info(f"✅ AI use set — {use_key} · {pid or 'no profile'}")
        return AiUseSetResult(key=use_key, profile_id=pid)


class AiUsesForgetTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "ai_uses_forget"
    description = "Forget a use an extension no longer declares (drops its key from ai.uses)"
    params = {
        "key": ToolParam(str, "The use, '<extension>:<use id>'"),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, key: str, workspace: str | None = None) -> AiUseForgetResult:
        _wid, path = _workspace(workspace)
        use_key = key.strip()
        uses = dict(_prefs(path).ai.uses)
        if use_key not in uses:
            return AiUseForgetResult(key=use_key, forgotten=False)
        del uses[use_key]
        _write_prefs(path, {"ai.uses": uses})
        log.info(f"✅ AI use forgotten — {use_key}")
        return AiUseForgetResult(key=use_key, forgotten=True)


class AiUsesRefreshTool(Tool):
    """Needs the live ExtensionManager, so it runs in the server (CLI: through POST /invoke)."""

    runtime = True
    surfaces = frozenset({"cli", "http"})
    name = "ai_uses_refresh"
    description = "Ask connected extensions for their AI uses again (one extension, or all connected)"
    params = {
        "extension_id": ToolParam(str, "Only this extension (its id); all connected when empty", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def attach_runtime(self, ctx: Any) -> None:
        # Reason: the extensions are live connections in the running server (ExtensionManager).
        self._runtime = ctx

    def execute(self, **kwargs: Any) -> AiUsesRefreshResult:
        raise RuntimeError("ai_uses_refresh needs the running Hiro server (it asks connected extensions)")

    async def execute_async(self, extension_id: str | None = None, workspace: str | None = None) -> AiUsesRefreshResult:
        del workspace  # the running server's own workspace
        rt = getattr(self, "_runtime", None)
        manager = rt.comm_manager.ctx.extension_manager if rt is not None else None
        return await refresh_extension_uses(manager, extension_id)


async def refresh_extension_uses(manager: Any, extension_id: str | None = None) -> AiUsesRefreshResult:
    """Ask the connected extension(s) for ``extension.info`` again and keep their uses."""
    if manager is None:
        return AiUsesRefreshResult(note="Extensions aren't running in this Hiro")
    live = manager.snapshot()
    targets = [extension_id] if extension_id else list(live)
    if not targets:
        return AiUsesRefreshResult(note="No extension is connected now")
    result = AiUsesRefreshResult()
    for eid in targets:
        name = str((live.get(eid) or {}).get("name") or eid)
        try:
            info = await manager.refresh_info(eid)
        except ExtensionRequestError as exc:
            log.warning(f"⚠️ AI uses not refreshed — {name}", error=exc.message, code=exc.code)
            result.failed.append({"extension_id": eid, "extension": name, "error": exc.message})
            continue
        result.refreshed.append(
            {"extension_id": eid, "extension": str(info.get("name") or name), "uses": len(info.get("uses") or [])}
        )
    return result


class LocalServerCheckTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "local_server_check"
    description = (
        "Check a local model server (lm_studio or ollama): up or down, its models (which are loaded, which "
        "the core loaded), its settings; the model list is kept so AI profiles can point at them. Optionally "
        "save its address first. Offline is a normal result."
    )
    params = {
        "provider_id": ToolParam(str, "lm_studio or ollama"),
        "base_url": ToolParam(str, "Save this address first (e.g. http://192.168.1.90:1234)", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(
        self, provider_id: str, base_url: str | None = None, workspace: str | None = None
    ) -> LocalServerCheckResult:
        from ..services.ai_ask.local_servers import loaded_by_core

        wid, path = _workspace(workspace)
        pid = _local_kind(provider_id)
        store = CredentialStore(path, wid)
        if base_url and base_url.strip():
            store.set_local_endpoint(pid, base_url.strip())
        settings = _prefs(path).ai.local_server(pid)
        result = LocalServerCheckResult(
            provider_id=pid,
            base_url=local_server_url(path, pid, store=store),
            online=False,
            configured=store.is_configured(pid),
            checked_at=datetime.now(UTC).isoformat(),
            unload_idle_min=settings.unload_idle_min,
            context=settings.context,
            batch=settings.batch,
        )
        if not result.base_url:
            result.state, result.error = "no_address", "no address set"
            return result
        try:
            models = probe_local_models(pid, result.base_url)
        except LocalServerError as exc:
            log.warning(f"⚠️ Local server not reached — {pid} · offline", error=str(exc), base_url=result.base_url)
            result.state, result.error = "down", str(exc)
        else:
            save_discovered_models(path, pid, models)
            log.info(f"✅ Local server checked — {pid} · {len(models)} models", base_url=result.base_url)
            result.state, result.online = "up", True
        # Offline: what it said last time stays offered.
        kept = list_discovered_models(path, pid)
        ours = loaded_by_core(path, pid)  # only this process's (the server's, when the admin asks)
        result.models = [
            {**_model_row(m), "loaded_by_core": m.name in ours, "idle_s": int(ours[m.name]) if m.name in ours else None}
            for m in kept
        ]
        return result


class LocalServerSetTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "local_server_set"
    description = (
        "Set a local model server's address and how the core loads its models: minutes before an idle model "
        "the core loaded is unloaded, the context and batch it loads them with (LM Studio)"
    )
    params = {
        "provider_id": ToolParam(str, "lm_studio or ollama"),
        "base_url": ToolParam(str, "Its address (one per kind)", required=False),
        "unload_idle_min": ToolParam(int, "Unload a model the core loaded after this many idle minutes", required=False),
        "context": ToolParam(int, "Context length the core loads models with (a profile's num_ctx wins)", required=False),
        "batch": ToolParam(int, "Batch size the core loads models with (pictures need 2048+)", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(
        self,
        provider_id: str,
        base_url: str | None = None,
        unload_idle_min: int | None = None,
        context: int | None = None,
        batch: int | None = None,
        workspace: str | None = None,
    ) -> LocalServerSetResult:
        wid, path = _workspace(workspace)
        pid = _local_kind(provider_id)
        if base_url and base_url.strip():
            CredentialStore(path, wid).set_local_endpoint(pid, base_url.strip())
        current = _prefs(path).ai.local_server(pid).model_dump()
        asked = {"unload_idle_min": unload_idle_min, "context": context, "batch": batch}
        changes = {k: v for k, v in asked.items() if v is not None}
        if changes:
            # Validated by LocalServerSettings' bounds on write (preferences runtime).
            _write_prefs(path, {f"ai.local_servers.{pid}": {**current, **changes}})
        settings = _prefs(path).ai.local_server(pid)
        return LocalServerSetResult(
            provider_id=pid,
            base_url=local_server_url(path, pid, workspace_id=wid),
            unload_idle_min=settings.unload_idle_min,
            context=settings.context,
            batch=settings.batch,
        )


def _local_kind(provider_id: str) -> str:
    pid = (provider_id or "").strip()
    if pid not in DISCOVERABLE_LOCAL_PROVIDERS:
        raise ValueError(f"provider_id must be one of {', '.join(DISCOVERABLE_LOCAL_PROVIDERS)}")
    return pid


def _model_row(m: Any) -> dict[str, Any]:
    return {
        "id": m.id,
        "name": m.name,
        "display_name": m.display_name,
        "vision": m.vision,
        "reasoning": m.reasoning,
        "loaded": m.loaded,
        "seen_at": m.seen_at,
    }


class AiImportHomeHiroTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "ai_import_homehiro"
    description = (
        "Import HomeHiro's LLM profiles (a copy of homehiro.db) as AI profiles hh-<HomeHiro id>, its defaults as "
        "home:<use> uses and its local server addresses. dry_run shows what it would write."
    )
    params = {
        "db_path": ToolParam(str, "Path to a copy of HomeHiro's homehiro.db"),
        "dry_run": ToolParam(bool, "Only show what would be written", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, db_path: str, dry_run: bool = False, workspace: str | None = None) -> AiImportResult:
        from ..services.ai_ask.import_homehiro import apply_plan, read_plan

        wid, path = _workspace(workspace)
        plan = read_plan(Path(db_path).expanduser())
        if not dry_run:
            apply_plan(path, plan, workspace_id=wid)
            log.info(
                f"✅ HomeHiro AI profiles imported — {len(plan.profiles)} profiles, {len(plan.uses)} uses",
                servers=list(plan.servers),
            )
        return AiImportResult(**plan.to_dict(), dry_run=bool(dry_run))


class AiUsageImportHomeHiroTool(Tool):
    surfaces = frozenset({"cli", "http"})
    name = "ai_usage_import_homehiro"
    description = (
        "Add HomeHiro's LLM usage history (a copy of homehiro.db, its llmtotal rows) to the core's AI usage under "
        "the source home — only the hours before the core counted Home itself, so running it again adds nothing. "
        "dry_run shows what it would add."
    )
    params = {
        "db_path": ToolParam(str, "Path to a copy of HomeHiro's homehiro.db"),
        "dry_run": ToolParam(bool, "Only show what would be added", required=False),
        "workspace": ToolParam(str, "Workspace name (default: registry default)", required=False),
    }

    def execute(self, db_path: str, dry_run: bool = False, workspace: str | None = None) -> AiUsageImportResult:
        from ..services.ai_usage.import_homehiro import import_usage

        _wid, path = _workspace(workspace)
        done = import_usage(path, _prefs(path), Path(db_path).expanduser(), dry_run=bool(dry_run))
        if done.written:
            log.info(
                f"✅ HomeHiro AI usage imported — {done.imported} rows, {done.requests} requests",
                cost=round(done.cost, 4),
                first_hour=done.first_hour,
                last_hour=done.last_hour,
            )
        return AiUsageImportResult(**done.to_dict(), dry_run=bool(dry_run))
