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


def test_wait_for_pid_error_includes_stderr_tail(tmp_path) -> None:
    stderr_log = tmp_path / "stderr.log"
    stderr_log.write_text("\n".join(f"line {i}" for i in range(45)), encoding="utf-8")

    try:
        process.wait_for_pid(
            tmp_path,
            "missing.pid",
            timeout=0,
            stderr_log=stderr_log,
        )
    except RuntimeError as exc:
        message = str(exc)
    else:
        raise AssertionError("wait_for_pid should fail when no PID file appears")

    assert "Recent stderr:" in message
    assert "line 5" in message
    assert "line 44" in message
    assert "line 0" not in message
