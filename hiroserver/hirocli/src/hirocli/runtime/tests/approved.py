"""For tests whose subject isn't approvals (Permissions phase 8): an app paired for real starts approved for nothing,
so a test about what it asks approves it for everything first, as an app from before approvals is."""

from __future__ import annotations

from pathlib import Path

from hirocli.domain import approvals
from hirocli.domain.extensions import list_paired_extensions


def approve_every_app(workspace: Path) -> None:
    for app in list_paired_extensions(workspace):
        approvals.write(workspace, app.extension_id, None)
