"""What the admin, the CLI and extensions read about AI profiles and uses (Phase 7a).

- ``profile_rows`` — each profile with its model's kind and provider, its limits in words, today's
  use, its fallback chain and whether it can be asked now (``ai.profiles``, ``ai_profiles_list``);
- ``use_rows`` — each paired extension's declared uses with the profile picked for each, marked
  ``new`` (not in its previous list) or ``removed`` (still in ``ai.uses`` but no longer declared)
  (``ai_uses_list``);
- ``extension_use_map`` — one extension's use id → profile id (``ai.profiles``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...domain.credential_store import CredentialStore
from ...domain.extensions import PairedExtension, list_paired_extensions
from ...domain.preferences import AiProfile, WorkspacePreferences, ai_fallback_chain
from .targets import resolve_target
from ..ai_usage.store import ProfileUsage, profile_usage


def budget_hint(profile: AiProfile, kind: str) -> str:
    """The profile's limits in words: "$1 a day · 2 at once"."""
    parts: list[str] = []
    if kind == "api" and profile.max_cost_day is not None:
        parts.append(f"${profile.max_cost_day:g} a day")
    if kind in ("plan", "local") and profile.max_per_hour is not None:
        parts.append(f"{profile.max_per_hour} an hour")
    if not parts:
        parts.append("no limit")
    if profile.at_once > 1:
        parts.append(f"{profile.at_once} at once")
    return " · ".join(parts)


def profile_rows(
    workspace_path: Path,
    prefs: WorkspacePreferences,
    store: CredentialStore | None,
) -> list[dict[str, Any]]:
    profiles = prefs.ai.profiles
    rows: list[dict[str, Any]] = []
    for pid, profile in sorted(profiles.items(), key=lambda kv: kv[1].label.lower()):
        try:
            target = resolve_target(workspace_path, profile.model, store=store)
            kind, provider, provider_label, not_ready = target.kind, target.provider_id, target.provider_label, target.not_ready
        except ValueError as exc:
            kind, provider, provider_label, not_ready = "api", profile.model.partition(":")[0], "", str(exc)
        used: ProfileUsage = profile_usage(workspace_path, pid)
        rows.append(
            {
                "id": pid,
                "label": profile.label,
                "model": profile.model,
                "provider": provider,
                "provider_label": provider_label,
                "kind": kind,
                "thinking": profile.thinking,
                "temperature": profile.temperature,
                "max_tokens": profile.max_tokens,
                "num_ctx": profile.num_ctx,
                "instructions": profile.instructions,
                "budget": {
                    "max_cost_day": profile.max_cost_day,
                    "max_per_hour": profile.max_per_hour,
                    "at_once": profile.at_once,
                },
                "budget_hint": budget_hint(profile, kind),
                "today": {
                    "asks": used.asks_today,
                    "cost": round(used.cost_today, 6),
                    "this_hour": used.asks_this_hour,
                },
                "fallback": profile.fallback,
                "fallback_chain": ai_fallback_chain(profiles, pid)[1:],
                "ready": not_ready is None,
                "not_ready": not_ready,
            }
        )
    return rows


def extension_use_map(prefs: WorkspacePreferences, extension_name: str) -> dict[str, str | None]:
    """use id → profile id for one extension (from ``ai.uses``)."""
    prefix = f"{extension_name}:"
    return {key[len(prefix):]: pid for key, pid in prefs.ai.uses.items() if key.startswith(prefix)}


def use_rows(workspace_path: Path, prefs: WorkspacePreferences, *, connected: set[str] | None = None) -> list[dict[str, Any]]:
    """Per extension: its declared uses (new / ok) and the ``ai.uses`` keys it no longer declares (removed)."""
    out: list[dict[str, Any]] = []
    named: set[str] = set()
    for ext in list_paired_extensions(workspace_path):
        named.add(ext.name)
        out.append(_extension_uses(ext, prefs, connected))
    # Keys of extensions no longer paired: shown so Forget can drop them.
    orphans: dict[str, list[dict[str, Any]]] = {}
    for key, pid in sorted(prefs.ai.uses.items()):
        name, _, use_id = key.partition(":")
        if name in named:
            continue
        orphans.setdefault(name, []).append(_use_row(key, use_id, None, pid, "removed"))
    for name, uses in orphans.items():
        out.append(
            {"extension": name, "extension_id": None, "connected": False, "as_of": None, "version": "", "uses": uses}
        )
    return out


def _extension_uses(ext: PairedExtension, prefs: WorkspacePreferences, connected: set[str] | None) -> dict[str, Any]:
    declared = ext.declared_uses()
    before = set(ext.uses_before)
    rows: list[dict[str, Any]] = []
    declared_ids: set[str] = set()
    for use in declared:
        use_id = use["id"]
        declared_ids.add(use_id)
        key = f"{ext.name}:{use_id}"
        status = "ok" if use_id in before or (not before and key in prefs.ai.uses) else "new"
        rows.append(_use_row(key, use_id, use, prefs.ai.uses.get(key), status))
    prefix = f"{ext.name}:"
    for key, pid in sorted(prefs.ai.uses.items()):
        if key.startswith(prefix) and key[len(prefix):] not in declared_ids:
            rows.append(_use_row(key, key[len(prefix):], None, pid, "removed"))
    return {
        "extension": ext.name,
        "extension_id": ext.extension_id,
        "connected": ext.extension_id in connected if connected is not None else None,
        "as_of": ext.last_seen.isoformat().replace("+00:00", "Z") if ext.last_seen else None,
        "version": str(ext.info.get("version") or ""),
        "uses": rows,
    }


def _use_row(key: str, use_id: str, use: dict[str, Any] | None, profile_id: str | None, status: str) -> dict[str, Any]:
    return {
        "key": key,
        "id": use_id,
        "name": str((use or {}).get("name") or use_id),
        "pictures": int((use or {}).get("pictures") or 0),
        "sound": bool((use or {}).get("sound")),
        "json": bool((use or {}).get("json", True)),
        "profile_id": profile_id,
        "status": status,
    }
