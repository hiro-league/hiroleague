"""Log tail and search operations for the admin API."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hiro_commons.log import Logger

from hirocli.admin.shared.result import Result
from hirocli.runtime.request_methods import REGISTERED_REQUEST_METHOD_NAMES
from hirocli.tools.logs import (
    LogSearchTool,
    LogTailTool,
    find_last_server_session_start_ts,
    _collect_log_files,
    _file_has_content,
    _read_tail_rows,
    _resolve_gateway_instance_path,
    _resolve_gateway_log_dir,
    _resolve_log_dir,
    _segment_to_key_value,
    _split_extra_segments,
    pretty_print_log_value,
)

# Initial window size matches legacy admin logs page.
INITIAL_TAIL_LINES = 500

_log = Logger.get("ADMIN")


@dataclass
class LogsLayoutInfo:
    """Filesystem snapshot for filter UI (channels, optional sources)."""

    available_channels: list[str]
    has_gateway: bool
    has_cli: bool


@dataclass
class LogTailSnapshot:
    """Rows + byte offsets for incremental tail."""

    rows: list[dict[str, Any]]
    file_offsets: dict[str, int]


class LogsService:
    """Facade over log reading tools."""

    def resolve_gateway_log_dir_fallback(self) -> Path | None:
        """When AdminContext has no gateway log dir, resolve like legacy logs page (tool-backed)."""
        try:
            return _resolve_gateway_log_dir()
        except Exception as exc:
            _log.warning(
                "⚠️ Gateway log dir fallback failed — HiroAdmin logs may omit gateway source",
                error=str(exc),
            )
            return None

    def split_log_extra_segments(self, extra: str) -> list[str]:
        """Parse CSV ``extra`` field into segments (tool helper; keeps UI free of tool imports)."""
        return _split_extra_segments(extra)

    def log_segment_key_value(self, seg: str) -> tuple[str, str]:
        return _segment_to_key_value(seg)

    def pretty_print_log_field(self, value: str) -> tuple[bool, str]:
        return pretty_print_log_value(value)

    def layout_info(
        self,
        log_dir: Path,
        gateway_log_dir: Path | None,
    ) -> Result[LogsLayoutInfo]:
        """Discover channel log stems and whether gateway/cli logs exist."""
        try:
            available_channels = [
                f.stem.removeprefix("channel-")
                for f in sorted(log_dir.glob("channel-*.log"))
            ]
            has_gateway = (
                (
                    gateway_log_dir is not None
                    and (gateway_log_dir / "gateway.log").exists()
                )
                or (
                    (gateway_instance_path := _resolve_gateway_instance_path()) is not None
                    and _file_has_content(gateway_instance_path / "stderr.log")
                )
            )
            has_cli = (log_dir / "cli.log").exists()
            return Result.success(
                LogsLayoutInfo(
                    available_channels=available_channels,
                    has_gateway=has_gateway,
                    has_cli=has_cli,
                )
            )
        except Exception as exc:
            return Result.failure(str(exc))

    def tail_initial(
        self,
        workspace: str | None,
        *,
        lines: int = INITIAL_TAIL_LINES,
        last_session_only: bool = False,
        since_seconds_ago: int | None = None,
    ) -> Result[LogTailSnapshot]:
        """Load the last *lines* rows from all sources (no prior offsets).

        When *last_session_only* is True, rows are limited to timestamps at/after the latest
        ``🚀 Hiro Server starting`` line in ``server.log`` (if that line exists).
        Otherwise, if *since_seconds_ago* is set, rows are limited to the last that many seconds.
        """
        try:
            min_ts: float | None = None
            if last_session_only:
                min_ts = find_last_server_session_start_ts(workspace)
            elif since_seconds_ago is not None:
                min_ts = time.time() - float(since_seconds_ago)
            exec_kwargs: dict[str, Any] = dict(
                source="all",
                lines=lines,
                workspace=workspace,
            )
            if min_ts is not None:
                exec_kwargs["min_timestamp"] = min_ts
            result = LogTailTool().execute(**exec_kwargs)
            return Result.success(
                LogTailSnapshot(rows=list(result.rows), file_offsets=dict(result.file_offsets))
            )
        except Exception as exc:
            return Result.failure(str(exc))

    def tail_after_offsets(
        self,
        workspace: str | None,
        file_offsets: dict[str, int],
    ) -> Result[LogTailSnapshot]:
        """Append-only read since *file_offsets* (JSON round-trip same as tool)."""
        try:
            offsets_json = json.dumps(file_offsets) if file_offsets else None
            result = LogTailTool().execute(
                source="all",
                after_offsets=offsets_json,
                workspace=workspace,
            )
            return Result.success(
                LogTailSnapshot(rows=list(result.rows), file_offsets=dict(result.file_offsets))
            )
        except RuntimeError:
            # Tool / IO edge cases during rapid file rotation — treat as empty poll.
            return Result.success(LogTailSnapshot(rows=[], file_offsets=dict(file_offsets)))
        except Exception as exc:
            return Result.failure(str(exc))

    def search(
        self,
        workspace: str | None,
        query: str,
    ) -> Result[list[dict[str, Any]]]:
        """Full-text search across message and extra (server-side tool)."""
        q = (query or "").strip()
        if not q:
            return Result.failure("Search query is empty.")
        try:
            result = LogSearchTool().execute(
                source="all",
                query=q,
                workspace=workspace,
            )
            return Result.success(list(result.rows))
        except Exception as exc:
            return Result.failure(str(exc))

    def search_filtered(
        self,
        workspace: str | None,
        *,
        query: str | None = None,
        device_id: str | None = None,
        msg_id: str | None = None,
        method: str | None = None,
    ) -> Result[list[dict[str, Any]]]:
        """Full-text search combined with structured scope filters (AND).

        At least one of ``query`` (non-empty) or a scope field must be provided.
        """
        q = (query or "").strip()
        did = (device_id or "").strip() or None
        mid = (msg_id or "").strip() or None
        meth = (method or "").strip() or None
        if not q and not any([did, mid, meth]):
            return Result.failure(
                "Provide a non-empty search query or at least one scope filter "
                "(device_id, msg_id, method)."
            )
        try:
            result = LogSearchTool().execute(
                source="all",
                query=q or None,
                device_id=did,
                msg_id=mid,
                method=meth,
                workspace=workspace,
            )
            return Result.success(list(result.rows))
        except Exception as exc:
            return Result.failure(str(exc))

    def filter_by_scope(
        self,
        workspace: str | None,
        *,
        device_id: str | None = None,
        msg_id: str | None = None,
        method: str | None = None,
    ) -> Result[list[dict[str, Any]]]:
        """Exact-match filter by structured scope fields (device / message / request type).

        Filters AND together: pass only the fields you want to constrain.
        Results are sorted by timestamp and cover all log sources.
        """
        did = (device_id or "").strip() or None
        mid = (msg_id or "").strip() or None
        meth = (method or "").strip() or None
        if not any([did, mid, meth]):
            return Result.failure("At least one scope filter (device_id, msg_id, method) is required.")
        try:
            result = LogSearchTool().execute(
                source="all",
                device_id=did,
                msg_id=mid,
                method=meth,
                workspace=workspace,
            )
            return Result.success(list(result.rows))
        except Exception as exc:
            return Result.failure(str(exc))

    def discover_methods(self, workspace: str | None) -> Result[list[str]]:
        """Return RPC ``method`` names for the admin dropdown.

        Merges the server's registered JSON-RPC methods with distinct ``scope_method``
        values from the recent log tail so unknown/custom methods still appear.
        """
        try:
            log_dir = _resolve_log_dir(workspace)
            gateway_log_dir = _resolve_gateway_log_dir()
            files = _collect_log_files(log_dir, gateway_log_dir, "all")
            methods: set[str] = set(REGISTERED_REQUEST_METHOD_NAMES)
            for file_path, src_label in files:
                rows, _ = _read_tail_rows(file_path, src_label, INITIAL_TAIL_LINES)
                for row in rows:
                    m = row.get("scope_method", "")
                    if isinstance(m, str) and m.strip():
                        methods.add(m.strip())
            return Result.success(sorted(methods))
        except Exception as exc:
            return Result.failure(str(exc))
