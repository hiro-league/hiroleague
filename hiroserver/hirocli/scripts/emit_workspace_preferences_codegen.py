"""Emit workspace-preferences JSON Schema + defaults for admin_frontend codegen."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from hirocli.domain.preferences_schema import (
    workspace_preferences_defaults,
    workspace_preferences_json_schema,
)


def write_lf(path, data) -> None:
    """newline="\n": LF on Windows too, like the node generators and .gitattributes (CRLF here left the generated files
    listed as modified with an empty diff, and hiro-work merge stopped on them)."""
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")


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
    write_lf(args.schema_out, schema)

    defaults = workspace_preferences_defaults()
    write_lf(args.defaults_out, defaults)

    from hirocli.domain.preferences_schema import workspace_preferences_field_map

    field_map = workspace_preferences_field_map()
    write_lf(args.field_schema_out, field_map)


if __name__ == "__main__":
    main()
