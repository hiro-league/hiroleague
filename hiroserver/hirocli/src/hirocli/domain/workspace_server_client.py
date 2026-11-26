"""HTTP client for the workspace Hiro server lifecycle API (localhost).

Admin UI and CLI use this to call ``POST /invoke`` on the running server —
e.g. ``message_send``, which needs an in-process CommunicationManager.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from hiro_commons.process import is_running, read_pid

from hirocli.constants import PID_FILENAME
from hirocli.domain.config import load_config

if TYPE_CHECKING:
    from hirocli.domain.packages import Package


def workspace_server_invoke_url(workspace_path: Path) -> str:
    cfg = load_config(workspace_path)
    host = (cfg.http_host or "127.0.0.1").strip() or "127.0.0.1"
    return f"http://{host}:{cfg.http_port}"


def require_workspace_server_running(workspace_path: Path) -> None:
    pid = read_pid(workspace_path, PID_FILENAME)
    if not is_running(pid):
        raise RuntimeError(
            "Hiro workspace server is not running. Start it with `hiro start`, then retry."
        )


def post_invoke_sync(
    workspace_path: Path,
    tool: str,
    params: dict[str, Any],
    *,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    """POST ``/invoke``; return the tool result dict. Raises on transport or HTTP error."""
    require_workspace_server_running(workspace_path)
    base = workspace_server_invoke_url(workspace_path).rstrip("/")
    url = f"{base}/invoke"
    with httpx.Client(timeout=timeout_seconds) as client:
        response = client.post(url, json={"tool": tool, "params": params})
    if response.status_code >= 400:
        detail = response.text.strip() or response.reason_phrase
        raise RuntimeError(f"Hiro server /invoke failed ({response.status_code}): {detail}")
    body = response.json()
    return dict(body["result"])


def put_package_sync(workspace_path: Path, package: Package, *, timeout_seconds: float = 300.0) -> str:
    """Hand a package's wheels to the running core (``PUT /packages``): the app's wheel, then its libraries; returns
    its id. The core's account may not read the person's files (a service core on Windows can't read their
    Downloads), so the bytes travel, not a path."""
    require_workspace_server_running(workspace_path)
    url = f"{workspace_server_invoke_url(workspace_path).rstrip('/')}/packages"
    package_id = ""
    with httpx.Client(timeout=timeout_seconds) as client:
        for path in (package.path, *package.libraries):
            params = {"file": path.name, **({"package": package_id} if package_id else {})}
            with path.open("rb") as body:
                response = client.put(url, params=params, content=body,
                                      headers={"content-type": "application/octet-stream"})
            if response.status_code >= 400:
                detail = response.text.strip() or response.reason_phrase
                raise RuntimeError(f"Hiro server /packages failed ({response.status_code}): {detail}")
            package_id = str(response.json()["package"])
    return package_id
