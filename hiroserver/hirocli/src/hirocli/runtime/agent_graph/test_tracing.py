"""Tests for the LangSmith trace-span helpers."""

from __future__ import annotations

from hirocli.runtime.agent_graph import tracing
from hirocli.runtime.agent_graph.tracing import traced_run


def test_traced_run_gated_off_yields_none_without_touching_langsmith(monkeypatch) -> None:
    """``when=False`` short-circuits before any tracing check, so a leg known to do no
    traceable work never posts a (hollow) span — the empty-trace fix relies on this."""

    def _boom() -> bool:
        raise AssertionError("_tracing_enabled must not run when gated off")

    monkeypatch.setattr(tracing, "_tracing_enabled", _boom)

    with traced_run("memory_eval_set_ingestion", when=False) as rt:
        assert rt is None


def test_traced_run_gated_on_consults_tracing_state(monkeypatch) -> None:
    """``when=True`` (the default) falls through to the normal tracing check; with tracing
    off it still no-ops (yields None) exactly as before."""
    monkeypatch.setattr(tracing, "_tracing_enabled", lambda: False)

    with traced_run("memory_eval_set_questions", when=True) as rt:
        assert rt is None
