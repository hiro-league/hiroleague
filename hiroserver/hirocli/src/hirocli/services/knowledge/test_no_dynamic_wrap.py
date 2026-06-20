"""Regression: knowledge builder must not use manual dynamic node wrapping.

Auto-wrap via ``NodeGroup.__init_subclass__`` is the single supported path; any
``_wrap_dynamic_node`` site in ``agent/`` is the old style and would bypass the prefix
mechanism (``_ledger_label_prefix``) silently.
"""

from __future__ import annotations

from pathlib import Path


def test_agent_package_has_no_wrap_dynamic_node() -> None:
    agent_dir = Path(__file__).resolve().parent / "agent"
    offenders = [
        py.name
        for py in agent_dir.glob("*.py")
        if "_wrap_dynamic_node" in py.read_text(encoding="utf-8")
    ]
    assert offenders == [], (
        f"agent/{offenders} use manual dynamic-node wrapping; rely on NodeGroup auto-wrap instead"
    )
