"""Preferences persistence — load/save ``preferences.json`` and publish change events."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from hiro_commons.constants.storage import PREFERENCES_FILENAME

from ..events import DomainEvent, DomainEventType, get_domain_event_bus
from .defaults import PROMPT_DEFAULTS
from .diff import compute_effective_changes
from .models import WorkspacePreferences

logger = logging.getLogger(__name__)


def _notify_preferences_saved(
    workspace_path: Path,
    prefs: "WorkspacePreferences",
    *,
    effective_changes: dict[str, tuple[Any, Any]] | None = None,
) -> None:
    """Publish that ``preferences.json`` was written.

    ``effective_changes`` maps leaf dot-paths to ``(old, new)`` tuples for values
    that actually differed between the previous and new persisted state. Empty
    dict ⇒ a no-op save (still published so subscribers can observe writes).
    """
    get_domain_event_bus().publish(
        DomainEvent(
            type=DomainEventType.PREFERENCES_SAVED,
            workspace_path=workspace_path,
            payload={
                "prefs": prefs,
                "effective_changes": dict(effective_changes or {}),
            },
        )
    )


def preferences_file(workspace_path: Path) -> Path:
    return workspace_path / PREFERENCES_FILENAME


def load_preferences(workspace_path: Path) -> WorkspacePreferences:
    f = preferences_file(workspace_path)
    if f.exists():
        text = f.read_text(encoding="utf-8")
        # A file older than v5 is converted once: v3 → v4 (AI profiles for Hiro's jobs), then v4 → v5
        # (embedding and reranker profiles); a v5 file validates exactly as before.
        if '"version"' not in text or _raw_version(text) < 5:
            return _load_converting(workspace_path, text)
        return WorkspacePreferences.model_validate_json(text)
    # Missing file: use structural defaults and persist so the workspace always has a real prefs file.
    prefs = WorkspacePreferences()
    save_preferences(workspace_path, prefs)
    logger.info(
        "⚠️ Persisted preferences — workspace · defaults (preferences.json was missing)",
        extra={
            "content_hint": "structural defaults written to disk",
            "workspace_path": str(workspace_path.resolve()),
        },
    )
    return prefs


def _raw_version(text: str) -> int:
    """The raw file's ``version`` (0 when unreadable; validation then reports the real problem)."""
    try:
        data = json.loads(text)
        return int(data.get("version") or 0) if isinstance(data, dict) else 5
    except (ValueError, TypeError, AttributeError):
        return 5  # not JSON: let model_validate_json raise its usual error


def _load_converting(workspace_path: Path, text: str) -> WorkspacePreferences:
    """The one-time conversions, oldest first: v3 → v4 (``convert_v4``) when older than v4, then v4 → v5
    (``convert_v5``). Converted and validated in memory, then saved as v5 and logged once per step; on any
    failure ``preferences.json`` is left as it was."""
    from .convert_v4 import convert_preferences_v3_to_v4, needs_conversion, write_converted_characters
    from .convert_v5 import convert_preferences_v4_to_v5

    data = json.loads(text)
    summary_v4 = None
    try:
        if needs_conversion(data):
            data, summary_v4 = convert_preferences_v3_to_v4(workspace_path, data)
        data, summary_v5 = convert_preferences_v4_to_v5(workspace_path, data)
        prefs = WorkspacePreferences.model_validate(data)
    except Exception as exc:
        logger.error(
            "❌ Preferences conversion failed — workspace · to v5 (preferences.json left as it was)",
            extra={"error": str(exc), "workspace_path": str(workspace_path.resolve())},
            exc_info=True,
        )
        raise
    # Written straight to disk (no preferences.saved event: this is the load, nothing changed live).
    _write_preferences_file(workspace_path, prefs)
    if summary_v4 is not None:
        write_converted_characters(summary_v4)
        logger.info(
            "✅ Preferences converted — workspace · v3 → v4 (AI profiles for Hiro's jobs) · %s",
            summary_v4.line(),
            extra={
                "ai_profiles": summary_v4.ai_profiles,
                "voice_profiles": summary_v4.voice_profiles,
                "backup": summary_v4.backup,
                "workspace_path": str(workspace_path.resolve()),
            },
        )
    logger.info(
        "✅ Preferences converted — workspace · v4 → v5 (embedding and reranker profiles) · %s",
        summary_v5.line(),
        extra={"backup": summary_v5.backup, "workspace_path": str(workspace_path.resolve())},
    )
    return prefs


def _write_preferences_file(workspace_path: Path, prefs: WorkspacePreferences) -> None:
    """Dump ``prefs`` to preferences.json (prompts at their default pruned, see below)."""
    workspace_path.mkdir(parents=True, exist_ok=True)
    data = prefs.model_dump(mode="json")
    _prune_default_prompts(data)
    preferences_file(workspace_path).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8",
    )


def _prune_default_prompts(data: dict[str, Any]) -> None:
    """Drop any editable prompt field whose value still equals its built-in default, in-place.

    Keeps a prompt left at (or restored to) default absent from preferences.json so it re-applies
    the code constant on load (a real reset that tracks future default edits). Only the known
    ``PROMPT_DEFAULTS`` paths are considered; a missing parent or non-default value is left alone."""
    for path, default_text in PROMPT_DEFAULTS.items():
        parts = path.split(".")
        node: Any = data
        for part in parts[:-1]:
            node = node.get(part) if isinstance(node, dict) else None
            if not isinstance(node, dict):
                break
        else:
            leaf = parts[-1]
            if isinstance(node, dict) and node.get(leaf) == default_text:
                node.pop(leaf, None)


def save_preferences(
    workspace_path: Path,
    prefs: WorkspacePreferences,
    *,
    previous: WorkspacePreferences | None = None,
) -> None:
    """Persist ``prefs`` and publish ``preferences.saved`` with a precise diff.

    ``previous`` is the in-memory state before this write; callers that already
    hold it (e.g. ``WorkspacePreferencesRuntime.update_many``) should pass it
    to skip an extra disk read. When omitted, the existing file is parsed (if
    present) so the published ``effective_changes`` reflects real value
    transitions, not just "the file was rewritten".
    """
    workspace_path.mkdir(parents=True, exist_ok=True)

    if previous is None:
        # Reading the file directly avoids ``load_preferences``' "write defaults
        # if missing" side effect, which would recurse through save_preferences.
        f = preferences_file(workspace_path)
        if f.exists():
            try:
                previous = WorkspacePreferences.model_validate_json(
                    f.read_text(encoding="utf-8")
                )
            except Exception:
                previous = None

    effective_changes = compute_effective_changes(previous, prefs)
    _validate_pre_save_transition(workspace_path, previous, prefs)

    # Prune editable prompt fields still at their built-in default so they stay ABSENT from the
    # file and re-apply the code constant on every load — a true reset that auto-tracks future
    # default edits, instead of "Restore default" persisting a pinned copy (model_dump_json would
    # otherwise materialize every field). Only PROMPT_DEFAULTS paths are touched; all else dumps full.
    _write_preferences_file(workspace_path, prefs)
    _notify_preferences_saved(
        workspace_path, prefs, effective_changes=effective_changes,
    )


def check_embedder_transition(
    workspace_path: Path,
    previous: WorkspacePreferences,
    updated: WorkspacePreferences,
    *,
    error: type[Exception] = ValueError,
) -> None:
    """Raise ``error`` if a change would orphan stored (dimension-bound) vectors.

    The single source for the embedder-lock rule: once the knowledge collection has points, the model the
    knowledge embeds with can't change, and once the graph is indexed, the model the graph embeds with
    can't. The rule reads the MODEL each search ends up with (``resolve_*_embedder_model``), so it holds
    whatever changed it: another profile picked, the picked profile's model edited, or the profile removed.
    The runtime PATCH guard and the save-time guard both call it with their own exception type — so the rule
    (and the messages) live in one place, and this module owns the service imports."""
    from hirocli.services.knowledge import count_knowledge_points
    from hirocli.services.knowledge.graph.graph_index_marker import is_graph_indexed

    from .resolvers import resolve_graphiti_embedder_model, resolve_knowledge_embedder_model

    old, new = resolve_knowledge_embedder_model(previous), resolve_knowledge_embedder_model(updated)
    if old != new and count_knowledge_points(workspace_path) > 0:
        raise error(
            f"The knowledge embedder can't change from {old} to {new or 'none'} while the knowledge "
            "collection has documents: their vectors were made with it. Delete all knowledge documents first."
        )
    old, new = resolve_graphiti_embedder_model(previous), resolve_graphiti_embedder_model(updated)
    if old != new and is_graph_indexed(workspace_path):
        raise error(
            f"The memory graph's embedder can't change from {old} to {new or 'none'} while the graph has "
            "indexed data: its vectors were made with it. Reset the graph first."
        )


def _validate_pre_save_transition(
    workspace_path: Path,
    previous: WorkspacePreferences | None,
    prefs: WorkspacePreferences,
) -> None:
    """Save-time embedder guard — runs on every persist (see :func:`check_embedder_transition`). A first
    save (no previous file) changes nothing that was indexed."""
    if previous is not None:
        check_embedder_transition(workspace_path, previous, prefs)

