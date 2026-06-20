"""Pin the public re-export surface of ``hirocli.runtime.agent_graph.ledger`` (P1b)."""

from __future__ import annotations

from pathlib import Path

import hirocli.runtime.agent_graph.ledger as ledger

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "ledger_public_api.txt"


def test_ledger_public_api_matches_fixture() -> None:
    expected = _FIXTURE.read_text(encoding="utf-8").strip().splitlines()
    assert sorted(ledger.__all__) == expected


def test_ledger_public_api_gate_reddens_on_removal() -> None:
    """Negative guard: dropping an export must fail the fixture check."""
    expected = _FIXTURE.read_text(encoding="utf-8").strip().splitlines()
    drifted = [name for name in expected if name != "observe"]
    assert drifted != expected
