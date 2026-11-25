"""Live workspace preferences for the running server.

The domain ``preferences`` module owns the persisted Pydantic schema and file
I/O. This runtime wrapper keeps the current validated preferences in memory and
provides targeted path updates for admin/runtime callers.
"""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Any, get_args, get_origin

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
from hirocli.domain.preferences.io import check_embedder_transition


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


# The running server's runtime per workspace (registered by ServerContext). A tool that writes
# preferences (Phase 7a: ai_uses_set / ai_uses_forget) goes through it when the server runs in this
# process, so the server's in-memory copy never goes stale and a later admin PATCH can't write the
# old ``ai`` section back over the tool's change.
_LIVE: dict[str, WorkspacePreferencesRuntime] = {}


def register_live_preferences(runtime: WorkspacePreferencesRuntime) -> None:
    _LIVE[_runtime_key(runtime._workspace_path)] = runtime


def preferences_runtime_for(workspace_path: Path) -> WorkspacePreferencesRuntime:
    """The running server's runtime for this workspace, else a fresh one over the file."""
    live = _LIVE.get(_runtime_key(workspace_path))
    return live if live is not None else WorkspacePreferencesRuntime(workspace_path)


def _runtime_key(workspace_path: Path) -> str:
    try:
        return str(workspace_path.resolve())
    except OSError:
        return str(workspace_path)


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

        if schema is dict or get_origin(schema) is dict:
            if not isinstance(node, dict):
                raise PreferencePathError(f"Cannot update preference path: {path}")
            if is_last or _holds_plain_values(schema):
                # A map of plain values (ai.uses, voice.uses) is keyed by "<extension key>:<use>", and a publisher's
                # key has a dot (acme.weather): the rest of the path is that one key, never more levels.
                node[".".join(parts[index:])] = value
                return
            node = node.setdefault(part, {})
            schema = Any
            continue

        raise PreferencePathError(f"Unknown preference path: {path}")

    raise PreferencePathError(f"Unknown preference path: {path}")


def _field_schema(annotation: Any) -> Any:
    # `get_origin` handles `dict[str, T]`, `typing.Dict[...]`, etc. uniformly (vs. the raw
    # `__origin__` attribute, which isn't present on every typing form). A dict keeps its value type, which says
    # whether its keys may hold dots (_holds_plain_values).
    return annotation


def _holds_plain_values(schema: Any) -> bool:
    """A dict whose values are neither models nor dicts (``dict[str, str | None]``, ``dict[str, list[str]]``): its
    keys are its last level."""
    args = get_args(schema)
    if len(args) != 2:
        return False
    value = args[1]
    kinds = [a for a in (get_args(value) or (value,)) if a is not type(None)]
    return all(
        not (isinstance(k, type) and issubclass(k, BaseModel)) and k is not dict and get_origin(k) is not dict
        for k in kinds
    )


def _validate_knowledge_embedding_transition(
    workspace_path: Path,
    previous: WorkspacePreferences,
    updated: WorkspacePreferences,
    edits: dict[str, Any],
) -> None:
    """PATCH-time embedder guard — delegates to the shared rule (``io.check_embedder_transition``),
    raising ``PreferencePathError``. A thin wrapper so the runtime layer doesn't import the
    knowledge/graph services itself. The rule compares the model each search embeds with before and
    after, so any edit (a pick, a profile's model, a removed profile) is checked the same way."""
    del edits
    check_embedder_transition(workspace_path, previous, updated, error=PreferencePathError)
