"""Gateway instance lifecycle operations for the admin API."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from hirocli.tools.gateway import (
    GatewaySetupTool,
    GatewayStartTool,
    GatewayStatusTool,
    GatewayStopTool,
    GatewayTeardownTool,
)

from hirocli.admin.shared.result import Result
from hirocli.admin.shared.stderr_log import stderr_log_info


class GatewayService:
    """Facade over gateway tools (global instances, not workspace-scoped)."""

    def list_instances(self) -> Result[list[dict[str, Any]]]:
        try:
            result = GatewayStatusTool().execute()
        except Exception as exc:
            return Result.failure(str(exc))
        rows: list[dict[str, Any]] = []
        for inst in result.instances:
            row = asdict(inst)
            row.update(stderr_log_info(Path(inst.path)))
            rows.append(row)
        return Result.success(rows)

    def start(self, instance_name: str, *, verbose: bool = False) -> Result[tuple[bool, int | None]]:
        """Returns (already_running, pid)."""
        if not instance_name:
            return Result.failure("Instance name is required.")
        try:
            r = GatewayStartTool().execute(instance=instance_name, verbose=verbose)
        except Exception as exc:
            return Result.failure(str(exc))
        return Result.success((r.already_running, r.pid))

    def stop(self, instance_name: str) -> Result[bool]:
        """Returns True if the process was running and was stopped."""
        if not instance_name:
            return Result.failure("Instance name is required.")
        try:
            r = GatewayStopTool().execute(instance=instance_name)
        except Exception as exc:
            return Result.failure(str(exc))
        return Result.success(r.was_running)

    def setup_instance(
        self,
        *,
        name: str,
        desktop_public_key: str,
        port: int,
        host: str = "0.0.0.0",
        log_dir: str = "",
        make_default: bool = False,
        skip_autostart: bool = False,
        elevated_task: bool = False,
    ) -> Result[str]:
        """Success data is a notify-ready summary string."""
        if not name.strip():
            return Result.failure("Name is required.")
        if not desktop_public_key.strip():
            return Result.failure("Desktop public key is required.")
        try:
            result = GatewaySetupTool().execute(
                name=name.strip(),
                desktop_public_key=desktop_public_key.strip(),
                port=port,
                host=host,
                log_dir=log_dir,
                make_default=make_default,
                skip_autostart=skip_autostart,
                elevated_task=elevated_task,
            )
        except Exception as exc:
            return Result.failure(str(exc))
        msg_parts = [f"Port: {result.port}"]
        if result.autostart_registered:
            msg_parts.append(f"Autostart: {result.autostart_method}")
        summary = (
            f"Gateway '{result.instance_name}' created.  •  " + "  •  ".join(msg_parts)
        )
        return Result.success(summary)

    def teardown_instance(
        self,
        instance_name: str,
        *,
        purge: bool,
        elevated_task: bool = False,
    ) -> Result[str]:
        if not instance_name:
            return Result.failure("Instance name is required.")
        try:
            result = GatewayTeardownTool().execute(
                instance=instance_name,
                purge=purge,
                elevated_task=elevated_task,
            )
        except Exception as exc:
            return Result.failure(str(exc))
        parts: list[str] = []
        if result.stopped:
            parts.append("stopped")
        if result.autostart_removed:
            parts.append("autostart removed")
        if result.purged:
            parts.append("files deleted")
        suffix = f": {', '.join(parts)}" if parts else ""
        summary = f"Gateway '{result.instance_name}' removed{suffix}."
        return Result.success(summary)
