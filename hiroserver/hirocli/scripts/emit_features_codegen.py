"""Emit the frontend feature-registry.json from the Python feature ledger.

Mirrors emit_workspace_preferences_codegen.py — the admin_frontend gen script
invokes this via ``uv run python`` so the frontend gets a synchronously-importable
copy of the ledger (see admin_frontend/scripts/gen-features-registry.mjs).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hirocli.domain.features import feature_registry


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Path to write feature-registry.json (id -> {label, active, note})",
    )
    args = parser.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    registry = feature_registry()
    args.out.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
