"""Importing HomeHiro's LLM profiles into the core's AI profiles, once (contract §7, Phase 7a Part B).

Reads a copy of HomeHiro's ``homehiro.db`` (read-only): ``llmprofile``, ``llmdefault``, ``llmserver`` and,
for the Write text node, ``automationgraph``. Builds:

- **AI profiles**, ids ``hh-<LlmProfile.id>`` exactly (HomeHiro's copies keep their old profile id and send
  it as ``hh-<id>``), labels their names; provider ids mapped (``gemini`` → ``google``, ``openai``,
  ``claude_cli`` → ``claude_code``, ``codex_cli`` → ``codex``, ``local:<server id>`` → ``lm_studio`` /
  ``ollama`` by that server's kind); thinking mapped onto the core's levels (``on`` → medium, ``xhigh`` /
  ``max`` → high); a 0 limit (HomeHiro's "no limit") → none; fallbacks mapped through the new ids. An API
  model the catalog doesn't have is left out (with a note) and fallbacks to it are dropped; a chain longer
  than the core allows is cut.
- **ai.uses** ``home:<use>`` from ``llmdefault``; with no ``write`` default, the model most Write text
  nodes use becomes ``home:write`` (an imported profile on that model, else a new "Write text" profile).
- **Local server addresses**: one per kind (the one the profiles use most; others noted), into the
  credential store.

Plan tools are signed in again in the core (their logins don't move). A dry run returns the same plan and
writes nothing. Profiles with an id already in preferences are replaced; everything else stays.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ...domain.preferences import AI_MAX_FALLBACKS, AiProfile
from ...domain.preferences.models_ai import AI_PROFILE_ID, check_ai_model_id

PROVIDERS = {"gemini": "google", "openai": "openai", "claude_cli": "claude_code", "codex_cli": "codex"}
SERVER_KINDS = {"lmstudio": "lm_studio", "ollama": "ollama"}
THINKING = {
    "none": "off", "off": "off", "minimal": "minimal", "low": "low", "medium": "medium", "high": "high",
    "xhigh": "high", "max": "high", "on": "medium",
}
WRITE_NODE = "llm"  # HomeHiro's Write text node def id
WRITE_DEFAULT_MODEL = "gemini-3.8-flash"  # what a Write text node without a model used


@dataclass
class ImportPlan:
    profiles: dict[str, dict[str, Any]] = field(default_factory=dict)  # new id → AI profile fields
    from_ids: dict[str, str] = field(default_factory=dict)  # HomeHiro id → new id
    uses: dict[str, str] = field(default_factory=dict)  # "home:<use>" → new id
    servers: dict[str, str] = field(default_factory=dict)  # lm_studio / ollama → address
    notes: list[str] = field(default_factory=list)
    written: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ImportError_(ValueError):  # noqa: N801 - not the builtin ImportError
    """The file isn't a HomeHiro database the import can read."""


def read_plan(db_file: Path) -> ImportPlan:
    """What importing ``db_file`` would write (pure read)."""
    if not db_file.is_file():
        raise ImportError_(f"No such file: {db_file}")
    try:
        conn = sqlite3.connect(f"file:{db_file.as_posix()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise ImportError_(f"Can't open {db_file}: {exc}") from exc
    conn.row_factory = sqlite3.Row
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "llmprofile" not in tables:
            raise ImportError_(f"{db_file} has no llmprofile table: not a HomeHiro database?")
        profiles = [dict(r) for r in conn.execute("SELECT * FROM llmprofile ORDER BY name")]
        defaults = [dict(r) for r in conn.execute("SELECT * FROM llmdefault")] if "llmdefault" in tables else []
        servers = [dict(r) for r in conn.execute("SELECT * FROM llmserver ORDER BY name")] if "llmserver" in tables else []
        graphs = [dict(r) for r in conn.execute("SELECT nodes FROM automationgraph")] if "automationgraph" in tables else []
    except sqlite3.Error as exc:
        raise ImportError_(f"Can't read {db_file}: {exc}") from exc
    finally:
        conn.close()
    return build_plan(profiles, defaults, servers, graphs)


def build_plan(
    profiles: list[dict[str, Any]],
    defaults: list[dict[str, Any]],
    servers: list[dict[str, Any]],
    graphs: list[dict[str, Any]],
) -> ImportPlan:
    plan = ImportPlan()
    server_kind: dict[str, str] = {}
    # One address per kind: the server the profiles use most wins (then the first by name).
    used = Counter(str(p.get("provider") or "").removeprefix("local:") for p in profiles)
    for s in sorted(servers, key=lambda s: (-used[str(s["id"])], str(s.get("name") or ""))):
        kind = SERVER_KINDS.get(str(s.get("kind") or ""))
        if kind is None:
            plan.notes.append(f"Server {s.get('name')!r}: unknown kind {s.get('kind')!r}, left out")
            continue
        server_kind[str(s["id"])] = kind
        address = str(s.get("address") or "").strip().rstrip("/")
        if kind in plan.servers:
            if plan.servers[kind] != address:
                plan.notes.append(
                    f"Server {s.get('name')!r} ({address}): the core keeps one {kind} address, {plan.servers[kind]} kept"
                )
            continue
        if address:
            plan.servers[kind] = address

    fallbacks: dict[str, str | None] = {}
    for p in profiles:
        # Exactly hh-<HomeHiro's id>: HomeHiro's side sends a copy's saved profile id that way.
        new_id = f"hh-{p['id']}"
        if not AI_PROFILE_ID.match(new_id):
            plan.notes.append(f"Profile {p.get('name')!r} left out: its id {p['id']!r} can't be an AI profile id")
            continue
        model = _model_id(p, server_kind, plan.notes)
        if model is None:
            continue
        fields = {
            "label": str(p.get("name") or new_id)[:80],
            "model": model,
            "thinking": THINKING.get(str(p.get("thinking") or "").lower()),
            "instructions": str(p.get("instructions") or ""),
            "max_cost_day": float(p["max_cost_day"]) if p.get("max_cost_day") else None,
            "max_per_hour": int(p["max_per_hour"]) if p.get("max_per_hour") else None,
            "at_once": min(4, max(1, int(p.get("at_once") or 1))),
        }
        try:
            AiProfile.model_validate(fields)
        except ValidationError as exc:
            plan.notes.append(f"Profile {p.get('name')!r} left out: {exc.errors()[0].get('msg')}")
            continue
        plan.from_ids[str(p["id"])] = new_id
        plan.profiles[new_id] = fields
        fallbacks[new_id] = str(p["fallback_id"]) if p.get("fallback_id") else None

    for new_id, old_fallback in fallbacks.items():
        if old_fallback is None:
            plan.profiles[new_id]["fallback"] = None
            continue
        mapped = plan.from_ids.get(old_fallback)
        if mapped is None:
            plan.notes.append(f"{plan.profiles[new_id]['label']}: its fallback wasn't imported, so it has none")
        plan.profiles[new_id]["fallback"] = mapped if mapped != new_id else None
    _cut_chains(plan)

    for d in defaults:
        mapped = plan.from_ids.get(str(d.get("profile_id") or ""))
        use = str(d.get("use") or "").strip()
        if not use:
            continue
        if mapped is None:
            plan.notes.append(f"Use {use!r}: its profile wasn't imported, so no profile is picked")
            continue
        plan.uses[f"home:{use}"] = mapped
    if "home:write" not in plan.uses:
        _write_text_use(plan, graphs)
    return plan


def _model_id(p: dict[str, Any], server_kind: dict[str, str], notes: list[str]) -> str | None:
    provider, model, name = str(p.get("provider") or ""), str(p.get("model") or ""), p.get("name")
    if provider.startswith("local:"):
        kind = server_kind.get(provider.removeprefix("local:"))
        if kind is None:
            notes.append(f"Profile {name!r} left out: its local server isn't in the database")
            return None
        mid = f"{kind}:{model}"
    elif provider in PROVIDERS:
        mid = f"{PROVIDERS[provider]}:{model}"
    else:
        notes.append(f"Profile {name!r} left out: unknown provider {provider!r}")
        return None
    try:
        check_ai_model_id(mid)
    except ValueError as exc:
        notes.append(f"Profile {name!r} left out: {exc}")
        return None
    return mid


def _cut_chains(plan: ImportPlan) -> None:
    """No loops and at most AI_MAX_FALLBACKS fallbacks after a profile: cut where a chain breaks that."""
    for pid in list(plan.profiles):
        seen = [pid]
        current = pid
        while (nxt := plan.profiles[current].get("fallback")) is not None:
            if nxt in seen or len(seen) > AI_MAX_FALLBACKS:
                plan.profiles[current]["fallback"] = None
                plan.notes.append(f"{plan.profiles[current]['label']}: fallback dropped (a loop or a chain too long)")
                break
            seen.append(nxt)
            current = nxt


def _write_text_use(plan: ImportPlan, graphs: list[dict[str, Any]]) -> None:
    """``home:write`` from the model the Write text nodes use most (HomeHiro picked a model, not a profile)."""
    models: Counter[str] = Counter()
    for g in graphs:
        try:
            nodes = json.loads(g.get("nodes") or "[]") if isinstance(g.get("nodes"), str) else (g.get("nodes") or [])
        except ValueError:
            continue
        for n in nodes:
            data = (n or {}).get("data") or {}
            if data.get("def") == WRITE_NODE:
                models[str((data.get("props") or {}).get("model") or WRITE_DEFAULT_MODEL)] += 1
    if not models:
        return
    model = models.most_common(1)[0][0]
    provider = "openai" if model.startswith("gpt-") else "google"
    mid = f"{provider}:{model}"
    same = next((pid for pid, f in plan.profiles.items() if f["model"] == mid), None)
    if same is not None:
        plan.uses["home:write"] = same
        return
    try:
        check_ai_model_id(mid)
    except ValueError as exc:
        plan.notes.append(f"Write text used {model!r}, which can't be a profile: {exc}")
        return
    new_id = "hh-write-text"
    plan.profiles[new_id] = {
        "label": "Write text", "model": mid, "thinking": "low", "instructions": "", "max_cost_day": None,
        "max_per_hour": None, "at_once": 1, "fallback": None,
    }
    plan.uses["home:write"] = new_id
    plan.notes.append(f"Write text used {model} directly: made the profile {new_id!r} for it")


def apply_plan(workspace_path: Path, plan: ImportPlan, *, workspace_id: str | None) -> None:
    """Write the plan: profiles and uses in one validated preferences write, then the server addresses."""
    from ...domain.credential_store import CredentialStore
    from ...runtime.preferences_runtime import preferences_runtime_for

    edits: dict[str, Any] = {f"ai.profiles.{pid}": fields for pid, fields in plan.profiles.items()}
    edits.update({f"ai.uses.{key}": pid for key, pid in plan.uses.items()})
    if edits:
        preferences_runtime_for(workspace_path).update_many(edits)
    if plan.servers and workspace_id is not None:
        store = CredentialStore(workspace_path, workspace_id)
        for kind, address in plan.servers.items():
            store.set_local_endpoint(kind, address)
    plan.written = True
