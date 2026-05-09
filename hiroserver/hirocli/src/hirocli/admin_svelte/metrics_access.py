"""Read global metrics collector handle from the running HTTP app (admin-only bridge)."""

from __future__ import annotations

from typing import Any


def _metrics_collector() -> Any:
    from hirocli.runtime.http_server import app as http_app

    return getattr(http_app.state, "metrics_collector", None)
