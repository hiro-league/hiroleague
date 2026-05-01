from __future__ import annotations

import sys
from pathlib import Path

from hiro_commons import process


def test_uv_python_cmd_uses_workspace_python(monkeypatch) -> None:
    workspace_root = Path("/tmp/hiro-workspace")

    monkeypatch.setattr(process, "find_workspace_root", lambda: workspace_root)

    assert process.uv_python_cmd() == [
        "uv",
        "run",
        "--directory",
        str(workspace_root),
        "python",
    ]


def test_uv_python_cmd_falls_back_to_current_interpreter(monkeypatch) -> None:
    monkeypatch.setattr(process, "find_workspace_root", lambda: None)

    assert process.uv_python_cmd() == [sys.executable]
