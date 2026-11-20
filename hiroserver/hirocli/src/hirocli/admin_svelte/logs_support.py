"""Log directory layout and row shaping for admin log viewers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hirocli.admin.features.logs.service import LogsService
from hirocli.admin.shared.result import Result
from hirocli.domain.config import load_config, resolve_log_dir
from hirocli.domain.workspace import resolve_workspace
from hiro_commons.log import Logger

_log = Logger.get("ADMIN")


def _workspace_log_dir(workspace_id: str | None):
    entry, _ = resolve_workspace(workspace_id)
    ws_path = Path(entry.path)
    config = load_config(ws_path)
    return resolve_log_dir(ws_path, config)


def _shape_log_rows(rows: list[dict[str, Any]], service: LogsService) -> list[dict[str, Any]]:
    shaped: list[dict[str, Any]] = []
    for row in rows:
        next_row = dict(row)
        message = str(next_row.get("message", "") or "")
        message_ok, message_pretty = service.pretty_print_log_field(message)
        next_row["message_pretty"] = message_pretty if message_ok else None

        segments: list[dict[str, Any]] = []
        # A row read from a file carries its fields as pairs (a traceback holds spaces and "=": never split again)
        pairs = next_row.pop("fields", None)
        if pairs is None:
            raw_extra = str(next_row.get("extra", "") or "")
            pairs = [service.log_segment_key_value(seg) for seg in service.split_log_extra_segments(raw_extra)]
        for key, value in pairs:
            value_ok, value_pretty = service.pretty_print_log_field(value)
            segments.append(
                {
                    "key": key or None,
                    "value": value,
                    "pretty": value_pretty if value_ok else None,
                }
            )
        next_row["extra_segments"] = segments
        shaped.append(next_row)
    return shaped


def _logs_layout(workspace_id: str | None) -> Result[dict[str, Any]]:
    service = LogsService()
    try:
        log_dir = _workspace_log_dir(workspace_id)
        gateway_log_dir = service.resolve_gateway_log_dir_fallback()
        info = service.layout_info(log_dir, gateway_log_dir)
        if not info.ok or info.data is None:
            return Result.failure(info.error or "Failed to inspect log directory.")
        return Result.success(
            {
                "log_dir": str(log_dir),
                "available_channels": info.data.available_channels,
                "has_gateway": info.data.has_gateway,
                "has_cli": info.data.has_cli,
                "other_streams": info.data.other_streams,
            }
        )
    except Exception as exc:
        _log.warning("⚠️ Logs layout failed — HiroAdmin · logs", error=str(exc), exc_info=True)
        return Result.failure(str(exc))
