"""The core builds the memory engine's graph service from its preferences."""

from __future__ import annotations

import pytest

from hirocli.domain.preferences import WorkspacePreferences
from hirocli.services.knowledge.graph_factory import build_graph_service


def test_build_graph_service_none_when_backend_off(tmp_path) -> None:
    prefs = WorkspacePreferences()  # backend defaults to "off"
    assert build_graph_service(prefs, tmp_path) is None


def test_build_graph_service_none_when_no_model(tmp_path) -> None:
    prefs = WorkspacePreferences()
    prefs.graph.backend = "graphiti"
    # No llm.default_chat and no knowledge.answering.model → extraction resolves
    # None (before any catalog/credential lookup) → service not created.
    assert build_graph_service(prefs, tmp_path, workspace_id="w") is None


def test_graph_preferences_query_timeout_default_and_bounds() -> None:
    """The knob is an admin preference (no hardcoded params rule): default 60s, clamped 0–600."""
    import pytest as _pytest
    from pydantic import ValidationError

    from hirocli.domain.preferences import GraphPreferences

    assert GraphPreferences().query_timeout_s == 60
    assert GraphPreferences(query_timeout_s=0).query_timeout_s == 0  # 0 = unlimited
    with _pytest.raises(ValidationError):
        GraphPreferences(query_timeout_s=-1)
    with _pytest.raises(ValidationError):
        GraphPreferences(query_timeout_s=601)



class _FakeDeepSeek:
    """Records ``with_structured_output`` kwargs; renamed to ``ChatDeepSeek`` below, the name the
    core's compat helper keys on."""

    def __init__(self) -> None:
        self.extra_body = {"thinking": {"type": "enabled"}}
        self.calls: list[dict] = []

    def with_structured_output(self, schema: object, include_raw: bool = False, **kwargs: object) -> object:
        self.calls.append({"include_raw": include_raw, **kwargs})
        return object()


_FakeDeepSeek.__name__ = "ChatDeepSeek"


def test_graph_structured_output_uses_the_core_compat_helper() -> None:
    """DeepSeek thinking mode 400s on the forced tool_choice; the graph's structured output goes
    through the core's compat helper, which falls back to json_mode."""
    from hirocli.services.knowledge.graph_factory import _structured_output

    model = _FakeDeepSeek()
    _structured_output(model, dict)
    assert model.calls == [{"include_raw": True, "method": "json_mode"}]
