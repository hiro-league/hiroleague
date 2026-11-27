"""A terminal run's restart comes back in the same terminal: the next server is this command's child, started again
each time it ends with the restart code, with the flags the terminal run was started with (issue 461)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hirocli.constants import ENV_ADMIN_UI, ENV_METRICS, ENV_SERVICE_MANAGER, SERVICE_RESTART_EXIT_CODE, TERMINAL_MANAGER
from hirocli.tools import server_control


class _Child:
    def __init__(self, ends: list[Any]) -> None:
        self.pid = 1234
        self._ends = ends

    def wait(self) -> int:
        end = self._ends.pop(0)
        if isinstance(end, BaseException):
            raise end
        return end


def _run(monkeypatch, tmp_path: Path, runs: list[list[Any]]) -> list[dict[str, str]]:
    started: list[dict[str, str]] = []

    def popen(cmd: list[str], env: dict[str, str]) -> _Child:
        started.append(env)
        return _Child(runs[len(started) - 1])

    monkeypatch.setattr(server_control.subprocess, "Popen", popen)
    monkeypatch.setenv(ENV_METRICS, "1")  # the terminal's own environment: the run's flags win
    server_control.restart_in_terminal(tmp_path, workspace_name="home", admin=True, metrics=False)
    return started


def test_each_restart_starts_the_server_again_until_it_ends_for_good(monkeypatch, tmp_path: Path) -> None:
    started = _run(monkeypatch, tmp_path, [[SERVICE_RESTART_EXIT_CODE], [SERVICE_RESTART_EXIT_CODE], [0]])
    assert len(started) == 3
    env = started[0]
    assert env[ENV_SERVICE_MANAGER] == TERMINAL_MANAGER  # its own restarts exit with the code instead of spawning
    assert env[ENV_ADMIN_UI] == "1" and ENV_METRICS not in env


def test_ctrl_c_lets_the_server_stop_by_itself(monkeypatch, tmp_path: Path) -> None:
    killed: list[int] = []
    monkeypatch.setattr(server_control, "kill_process", lambda pid, include_tree: killed.append(pid))
    started = _run(monkeypatch, tmp_path, [[KeyboardInterrupt(), 0]])
    assert len(started) == 1 and killed == []  # one Ctrl-C: the server got it too and stopped
