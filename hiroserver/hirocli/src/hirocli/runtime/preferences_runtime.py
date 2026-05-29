"""Live workspace preferences for the running server.

The domain ``preferences`` module owns the persisted Pydantic schema and file
I/O. This runtime wrapper keeps the current validated preferences in memory and
provides targeted path updates for admin/runtime callers.
"""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Any

from pydantic import BaseModel, ValidationError

from hirocli.domain.preferences import (
    ChatPreferences,
    KnowledgePreferences,
    LLMPreferences,
    MediaPreferences,
    MemoryPreferences,
    WorkspacePreferences,
    load_preferences,
    save_preferences,
)


class PreferencePathError(ValueError):
    """Raised when a preference path is unknown or cannot be updated."""


class WorkspacePreferencesRuntime:
    """In-memory current workspace preferences with validated targeted writes."""

    def __init__(
        self,
        workspace_path: Path,
        *,
        initial: WorkspacePreferences | None = None,
    ) -> None:
        self._workspace_path = workspace_path
        self._lock = RLock()
        self._current = initial.model_copy(deep=True) if initial is not None else load_preferences(workspace_path)

    @property
    def current(self) -> WorkspacePreferences:
        """Return the current validated preferences object as a defensive copy."""
        with self._lock:
            return self._current.model_copy(deep=True)

    @property
    def llm(self) -> LLMPreferences:
        return self.current.llm

    @property
    def media(self) -> MediaPreferences:
        return self.current.media

    @property
    def memory(self) -> MemoryPreferences:
        return self.current.memory

    @property
    def knowledge(self) -> KnowledgePreferences:
        return self.current.knowledge

    @property
    def chat(self) -> ChatPreferences:
        return self.current.chat

    def reload(self) -> WorkspacePreferences:
        """Reload preferences from disk and replace the in-memory current value."""
        prefs = load_preferences(self._workspace_path)
        with self._lock:
            self._current = prefs.model_copy(deep=True)
            return self._current.model_copy(deep=True)

    def update(self, path: str, value: Any) -> WorkspacePreferences:
        """Update one preference path, persist it, and replace the in-memory value."""
        return self.update_many({path: value})

    def update_many(self, edits: dict[str, Any]) -> WorkspacePreferences:
        """Apply multiple preference path edits atomically."""
        cleaned = {str(path).strip(): value for path, value in edits.items()}
        if not cleaned:
            raise PreferencePathError("At least one preference edit is required.")
        if any(not path for path in cleaned):
            raise PreferencePathError("Preference paths cannot be empty.")

        with self._lock:
            previous = self._current.model_copy(deep=True)
            data = previous.model_dump(mode="python")
            data["version"] = WorkspacePreferences().version
            for path, value in cleaned.items():
                _set_path(data, path, value)
            try:
                updated = WorkspacePreferences.model_validate(data)
            except ValidationError:
                raise
            _validate_knowledge_embedding_transition(self._workspace_path, previous, updated, cleaned)
            save_preferences(
                self._workspace_path,
                updated,
                previous=previous,
            )
            self._current = updated.model_copy(deep=True)
            return self._current.model_copy(deep=True)


def _set_path(root: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    if len(parts) == 1:
        field = parts[0]
        if field not in WorkspacePreferences.model_fields:
            raise PreferencePathError(f"Unknown preference path: {path}")
        root[field] = value
        return
    if len(parts) < 2:
        raise PreferencePathError(f"Preference path must include a section and field: {path}")

    schema: Any = WorkspacePreferences
    node: Any = root

    for index, part in enumerate(parts):
        is_last = index == len(parts) - 1
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            fields = schema.model_fields
            if part not in fields:
                raise PreferencePathError(f"Unknown preference path: {path}")
            field = fields[part]
            if is_last:
                if not isinstance(node, dict):
                    raise PreferencePathError(f"Cannot update preference path: {path}")
                node[part] = value
                return
            if not isinstance(node, dict):
                raise PreferencePathError(f"Cannot update preference path: {path}")
            node = node.setdefault(part, {})
            schema = _field_schema(field.annotation)
            continue

        if schema is dict or getattr(schema, "__origin__", None) is dict:
            if not isinstance(node, dict):
                raise PreferencePathError(f"Cannot update preference path: {path}")
            if is_last:
                node[part] = value
                return
            node = node.setdefault(part, {})
            schema = Any
            continue

        raise PreferencePathError(f"Unknown preference path: {path}")

    raise PreferencePathError(f"Unknown preference path: {path}")


def _field_schema(annotation: Any) -> Any:
    origin = getattr(annotation, "__origin__", None)
    if origin is dict:
        return dict
    return annotation


def _validate_knowledge_embedding_transition(
    workspace_path: Path,
    previous: WorkspacePreferences,
    updated: WorkspacePreferences,
    edits: dict[str, Any],
) -> None:
    if "knowledge.default_embedding_model" not in edits:
        return
    old_value = previous.knowledge.default_embedding_model
    new_value = updated.knowledge.default_embedding_model
    if old_value == new_value:
        return
    from hirocli.services.knowledge.live_registry import count_knowledge_points

    point_count = count_knowledge_points(workspace_path)
    if point_count > 0:
        raise PreferencePathError(
            "knowledge.default_embedding_model cannot be changed while the knowledge collection has points. "
            "Delete all knowledge documents first."
        )
