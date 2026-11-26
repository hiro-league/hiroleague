"""Build Hello's test versions, for trying an upgrade (`hiro extension upgrade example.hello <package>`):

    uv run --project hiroserver python build-kit/test-app/variants.py --out <folder>

- **0.1.1, good:** a migration that adds a greeting; it upgrades.
- **0.1.2, broken migration:** its migration fails, so the trial refuses it and Hello never stops.
- **0.1.3, never answers:** its migration runs (it writes a greeting) and then it never starts, so the upgrade goes
  back: the data as it was at the stop, and 0.1.0 again.

Each is a copy of the test app with its version, its migration (and for 0.1.3 its start) changed, its lock made
again, then built by build-kit/package.py. Upgrades run from 0.1.0, so every migration follows the initial one;
try them in the order above (each one newer than 0.1.0, and the first two leave 0.1.0 in place).
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
INITIAL = "4599b07f0051"

MIGRATION = '''"""{doc}

Revision ID: {revision}
Revises: {initial}
"""
from alembic import op

revision = "{revision}"
down_revision = "{initial}"
branch_labels = None
depends_on = None


def upgrade() -> None:
{body}


def downgrade() -> None:
    op.execute("DELETE FROM greeting WHERE words LIKE 'from %'")
'''

VARIANTS = {
    "0.1.1": ("a greeting from 0.1.1", "    op.execute(\"INSERT INTO greeting (words) VALUES ('from 0.1.1')\")", False),
    "0.1.2": ("a migration that fails on purpose", "    raise RuntimeError('0.1.2: this migration fails on purpose')",
              False),
    "0.1.3": ("a greeting, then 0.1.3 never starts", "    op.execute(\"INSERT INTO greeting (words) VALUES ('from 0.1.3')\")",
              True),
}


def _variant(version: str, stage: Path) -> Path:
    doc, body, never_starts = VARIANTS[version]
    app = stage / f"hello-{version}"
    shutil.copytree(HERE, app, ignore=shutil.ignore_patterns(".venv", "data", "__pycache__", "node_modules", "variants.py"))
    backend = app / "backend"
    pyproject = backend / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8").replace('version = "0.1.0"', f'version = "{version}"', 1)

    def absolute(match: re.Match[str]) -> str:
        return f'{match[1]}"{(HERE / "backend" / match[2]).resolve().as_posix()}"'

    pyproject.write_text(re.sub(r'(path\s*=\s*)"([^"]+)"', absolute, text), encoding="utf-8")
    revision = f"b0000000{version.replace('.', '')}"
    (backend / "src" / "hello" / "migrations" / "versions" / f"{revision}_test_{version.replace('.', '_')}.py").write_text(
        MIGRATION.format(doc=doc, revision=revision, initial=INITIAL, body=body), encoding="utf-8")
    if never_starts:
        app_py = backend / "src" / "hello" / "app.py"
        app_py.write_text(app_py.read_text(encoding="utf-8").replace(
            "    migrate()\n", "    migrate()\n    raise RuntimeError('0.1.3 never starts, on purpose')\n", 1), encoding="utf-8")
    subprocess.run(["uv", "lock"], cwd=backend, check=True, capture_output=True)  # noqa: S607
    return app


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Build Hello's test versions for an upgrade.")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    sys.path.insert(0, str(HERE.parent))
    import package  # build-kit/package.py

    with tempfile.TemporaryDirectory(prefix="hello-variants-") as tmp:
        for version in VARIANTS:
            print(package.build(_variant(version, Path(tmp)), args.out.resolve(), ui_built=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
