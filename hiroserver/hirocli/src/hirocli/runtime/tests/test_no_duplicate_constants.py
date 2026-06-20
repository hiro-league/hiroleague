"""Guard against re-introducing duplicated graph helpers/constants (P2b).

Scans the agent-side node packages where these helpers would naturally drift back in:
``runtime/agent_graph/`` (chat side) AND ``services/knowledge/agent/`` (knowledge side).
``graph_kit.py`` is the single canonical owner; any definition elsewhere is the regression.
"""

from __future__ import annotations

import re
from pathlib import Path

_HIROCLI_SRC = Path(__file__).resolve().parents[2]
_SCAN_ROOTS = (
    _HIROCLI_SRC / "runtime" / "agent_graph",
    _HIROCLI_SRC / "services" / "knowledge" / "agent",
)

# Each symbol must appear as a definition at most once under the scanned roots —
# ``graph_kit.py`` owns them. Both the public (post-P2b) names and the old private
# (pre-P2b) names are listed so the duplicate-definition bug from `conversation.py`
# (where ``_AGENT_TOOL_ARGS_MAX`` was defined twice in the same file) cannot reappear.
_DUPLICATE_GUARD_SYMBOLS = (
    r"^AGENT_TOOL_ARGS_MAX\s*=",
    r"^AGENT_TOOL_RESULT_MAX\s*=",
    r"^def memory_text\(",
    r"^def tool_args_one_line\(",
    r"^def tool_result_bounded\(",
    r"^def tool_call_id\(",
    r"^def tool_call_name\(",
    r"^def tool_call_args\(",
    r"^def _memory_text\(",
    r"^def _tool_args_one_line\(",
    r"^def _tool_result_bounded\(",
    r"^def _tool_call_id\(",
    r"^def _tool_call_name\(",
    r"^def _tool_call_args\(",
    r"^_AGENT_TOOL_ARGS_MAX\s*=",
    r"^_AGENT_TOOL_RESULT_MAX\s*=",
)


def _definition_sites(pattern: str) -> list[str]:
    rx = re.compile(pattern)
    hits: list[str] = []
    for root in _SCAN_ROOTS:
        for path in sorted(root.rglob("*.py")):
            if path.name == "graph_kit.py":
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                if rx.search(line.strip()):
                    hits.append(f"{path.relative_to(_HIROCLI_SRC)}:{line.strip()}")
    return hits


def test_no_duplicate_graph_helper_definitions_outside_graph_kit() -> None:
    offenders: list[str] = []
    for pattern in _DUPLICATE_GUARD_SYMBOLS:
        sites = _definition_sites(pattern)
        if sites:
            offenders.extend(sites)
    assert not offenders, "Duplicate graph helpers/constants outside graph_kit.py:\n" + "\n".join(
        offenders
    )


def test_duplicate_guard_would_catch_a_reintroduced_definition(tmp_path: Path) -> None:
    """Negative guard: a fresh ``def memory_text(...)`` inside one of the scanned roots reddens."""
    pattern = r"^def memory_text\("
    rx = re.compile(pattern)
    fake = tmp_path / "fake_module.py"
    fake.write_text("def memory_text(item):\n    return ''\n", encoding="utf-8")
    assert rx.search(fake.read_text(encoding="utf-8").splitlines()[0].strip())
