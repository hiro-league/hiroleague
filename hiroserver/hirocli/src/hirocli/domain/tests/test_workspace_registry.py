"""Reading the workspace registry (domain/workspace.py): an unreadable one is said, never read as empty."""

from __future__ import annotations

from pathlib import Path

import pytest

from hirocli.constants import ENV_DATA_DIR
from hirocli.domain import workspace


@pytest.mark.parametrize("denied_call", ["stat", "read_text"])
def test_a_registry_this_account_may_not_read_says_to_run_as_an_administrator(
    tmp_path: Path, monkeypatch, denied_call: str
) -> None:
    # A normal terminal with HIRO_DATA_DIR on the service's data folder was told "No workspaces configured. Run 'hiro
    # workspaces create' first." (a clean laptop, Nov 26, 2026): the folder admits only administrators. On the PC the
    # file's stat is what is denied; read_text stands for a folder that lets it be seen but not read.
    monkeypatch.setenv(ENV_DATA_DIR, str(tmp_path))
    registry = workspace.registry_path()
    registry.write_text("{}", encoding="utf-8")
    real = getattr(Path, denied_call)

    def denied(self: Path, *args, **kwargs):
        if self == registry:
            raise PermissionError(13, "Access is denied", str(self))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, denied_call, denied)
    with pytest.raises(workspace.WorkspaceError, match="administrator terminal"):
        workspace.resolve_workspace()


def test_no_registry_yet_still_says_to_create_a_workspace(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(ENV_DATA_DIR, str(tmp_path))
    with pytest.raises(workspace.WorkspaceError, match="No workspaces configured"):
        workspace.resolve_workspace()
