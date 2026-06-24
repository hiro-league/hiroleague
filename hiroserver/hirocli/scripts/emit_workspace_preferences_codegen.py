"""Emit workspace-preferences JSON Schema + defaults for admin_frontend codegen."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hirocli.domain.preferences_schema import (
    workspace_preferences_defaults,
    workspace_preferences_json_schema,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--schema-out",
        type=Path,
        required=True,
        help="Path to write workspace-preferences.schema.json",
    )
    parser.add_argument(
        "--defaults-out",
        type=Path,
        required=True,
        help="Path to write workspace-preferences.defaults.json",
    )
    parser.add_argument(
        "--field-schema-out",
        type=Path,
        required=True,
        help="Path to write preferences-field-schema.json (flat path → field meta)",
    )
    args = parser.parse_args()

    args.schema_out.parent.mkdir(parents=True, exist_ok=True)
    args.defaults_out.parent.mkdir(parents=True, exist_ok=True)
    args.field_schema_out.parent.mkdir(parents=True, exist_ok=True)

    schema = workspace_preferences_json_schema()
    args.schema_out.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")

    defaults = workspace_preferences_defaults()
    args.defaults_out.write_text(json.dumps(defaults, indent=2) + "\n", encoding="utf-8")

    from hirocli.domain.preferences_schema import workspace_preferences_field_map

    field_map = workspace_preferences_field_map()
    args.field_schema_out.write_text(json.dumps(field_map, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
