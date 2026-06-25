"""Preferences persistence — load/save ``preferences.json`` and publish change events."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from hiro_commons.constants.storage import PREFERENCES_FILENAME

from .models import (
    PROMPT_DEFAULTS,
    WorkspacePreferences,
    _notify_preferences_saved,
    compute_effective_changes,
)

logger = logging.getLogger(__name__)


def preferences_file(workspace_path: Path) -> Path:
    return workspace_path / PREFERENCES_FILENAME


def load_preferences(workspace_path: Path) -> WorkspacePreferences:
    f = preferences_file(workspace_path)
    if f.exists():
        return WorkspacePreferences.model_validate_json(f.read_text(encoding="utf-8"))
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
    _validate_pre_save_transition(workspace_path, effective_changes)

    # Prune editable prompt fields still at their built-in default so they stay ABSENT from the
    # file and re-apply the code constant on every load — a true reset that auto-tracks future
    # default edits, instead of "Restore default" persisting a pinned copy (model_dump_json would
    # otherwise materialize every field). Only PROMPT_DEFAULTS paths are touched; all else dumps full.
    data = prefs.model_dump(mode="json")
    _prune_default_prompts(data)
    preferences_file(workspace_path).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    _notify_preferences_saved(
        workspace_path, prefs, effective_changes=effective_changes,
    )


def _validate_pre_save_transition(
    workspace_path: Path,
    effective_changes: dict[str, tuple[Any, Any]],
) -> None:
    transition = effective_changes.get("knowledge.default_embedding_model")
    if transition is None:
        return
    old_value, new_value = transition
    if old_value == new_value:
        return
    from hirocli.services.knowledge import count_knowledge_points

    if count_knowledge_points(workspace_path) > 0:
        raise ValueError(
            "knowledge.default_embedding_model cannot be changed while the knowledge collection has points. "
            "Delete all knowledge documents first."
        )


# ---------------------------------------------------------------------------
# Resolution — which canonical model id + tuning for a purpose?
# ---------------------------------------------------------------------------

