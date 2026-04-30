"""Helpers for surfacing detached-process stderr logs in admin rows."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def stderr_log_info(base_path: Path) -> dict[str, Any]:
    target = base_path / "stderr.log"
    try:
        stat = target.stat()
    except OSError:
        return {
            "stderr_log_path": str(target),
            "stderr_log_exists": False,
            "stderr_log_size": 0,
            "stderr_log_mtime": None,
            "stderr_log_recent": False,
        }

    mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
    return {
        "stderr_log_path": str(target),
        "stderr_log_exists": stat.st_size > 0,
        "stderr_log_size": stat.st_size,
        "stderr_log_mtime": mtime.isoformat(),
        "stderr_log_recent": datetime.now(timezone.utc) - mtime <= timedelta(hours=1),
    }
