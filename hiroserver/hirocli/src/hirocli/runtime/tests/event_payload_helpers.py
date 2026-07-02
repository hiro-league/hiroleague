"""Normalize graph event streams for payload contract snapshots (P2a)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
_REPLY_ID_PATTERN = re.compile(
    r"reply-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)

# Cross-language consumers of ``GRAPH_*`` custom-stream payloads (update when wiring changes):
# - hiroserver/hirocli/src/hirocli/runtime/graph_event_subscriber.py
# - hiroserver/hirocli/src/hirocli/runtime/tests/test_graph_event_subscriber.py


def normalize_event_stream(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Strip volatile ids and large binary fields so snapshots stay stable."""
    normalized: list[dict[str, Any]] = []
    for event in events:
        payload = dict(event.get("payload") or {})
        for key, value in list(payload.items()):
            if key == "audio_b64" and value:
                payload[key] = "<b64>"
            elif key == "elapsed_ms":
                # Volatile wall-clock timing — blank it so snapshots stay stable run-to-run (mirrors
                # the ledger snapshot's _VOLATILE_COLUMNS).
                payload[key] = 0
            elif isinstance(value, str):
                payload[key] = _REPLY_ID_PATTERN.sub("reply-<uuid>", value)
        normalized.append({"event": event.get("event"), "payload": payload})
    return normalized


def load_event_payload_fixture(scenario: str) -> list[dict[str, Any]]:
    path = _FIXTURES_DIR / f"event_payloads_{scenario}.json"
    return json.loads(path.read_text(encoding="utf-8"))
