"""Helpers for ledger row snapshot tests (P1b gate)."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from hirocli.runtime.agent_graph.ledger import GRAPH_LEDGER_COLUMNS

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
# Timing fields vary run-to-run; the gate compares everything else byte-for-byte.
_VOLATILE_COLUMNS = frozenset({"ts", "elapsed_ms"})
_REPLY_ID_PATTERN = re.compile(
    r"reply-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)


def _stable_preview(value: str) -> str:
    return _REPLY_ID_PATTERN.sub("reply-<uuid>", value)


def read_graph_log_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def normalize_rows(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Project to ``GRAPH_LEDGER_COLUMNS`` order and blank volatile timing fields."""
    normalized: list[dict[str, str]] = []
    for row in rows:
        projected = {column: str(row.get(column, "") or "") for column in GRAPH_LEDGER_COLUMNS}
        for column in _VOLATILE_COLUMNS:
            projected[column] = ""
        for column in ("input_preview", "output_preview"):
            projected[column] = _stable_preview(projected[column])
        normalized.append(projected)
    return normalized


def sort_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    return sorted(
        rows,
        key=lambda row: (
            str(row.get("step_index") or ""),
            str(row.get("sub_step") or ""),
            str(row.get("node") or ""),
            str(row.get("node_attempt") or ""),
        ),
    )


def load_ledger_fixture(scenario: str) -> list[dict[str, str]]:
    path = _FIXTURES_DIR / f"ledger_rows_{scenario}.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    return sort_rows([{column: str(row.get(column, "") or "") for column in GRAPH_LEDGER_COLUMNS} for row in rows])


def rows_to_fixture(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    return sort_rows(normalize_rows(rows))
