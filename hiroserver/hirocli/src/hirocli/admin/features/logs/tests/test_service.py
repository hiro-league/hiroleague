"""LogsService — mocked tools / tmp dirs; no NiceGUI."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from hirocli.admin.features.logs.service import LogsService
from hirocli.tools.logs import _read_tail_rows


def test_layout_info_channels_gateway_cli(tmp_path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "channel-alpha.log").write_text("", encoding="utf-8")
    (log_dir / "channel-beta.log").write_text("", encoding="utf-8")
    (log_dir / "cli.log").write_text("", encoding="utf-8")
    gw_dir = tmp_path / "gw"
    gw_dir.mkdir()
    (gw_dir / "gateway.log").write_text("", encoding="utf-8")

    r = LogsService().layout_info(log_dir, gw_dir)
    assert r.ok and r.data is not None
    assert r.data.available_channels == ["alpha", "beta"]
    assert r.data.has_cli is True
    assert r.data.has_gateway is True


def test_layout_info_no_gateway_file(tmp_path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    gw_dir = tmp_path / "gw"
    gw_dir.mkdir()

    with patch(
        "hirocli.admin.features.logs.service._resolve_gateway_instance_path",
        return_value=None,
    ):
        r = LogsService().layout_info(log_dir, gw_dir)
    assert r.ok and r.data is not None
    assert r.data.has_gateway is False


def test_layout_info_gateway_stderr_counts_as_gateway(tmp_path) -> None:
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    gw_dir = tmp_path / "gw-logs"
    gw_dir.mkdir()
    instance_dir = tmp_path / "gateway-instance"
    instance_dir.mkdir()
    (instance_dir / "stderr.log").write_text("Traceback boom\n", encoding="utf-8")

    with patch(
        "hirocli.admin.features.logs.service._resolve_gateway_instance_path",
        return_value=instance_dir,
    ):
        r = LogsService().layout_info(log_dir, gw_dir)

    assert r.ok and r.data is not None
    assert r.data.has_gateway is True


def test_gateway_stderr_tail_rows_are_plain_error_rows(tmp_path) -> None:
    stderr_log = tmp_path / "stderr.log"
    stderr_log.write_text("Traceback line\nUnicodeEncodeError: boom\n", encoding="utf-8")

    rows, offset = _read_tail_rows(stderr_log, "gateway", 10)

    assert offset == stderr_log.stat().st_size
    assert [row["source"] for row in rows] == ["gateway", "gateway"]
    assert [row["level"] for row in rows] == ["ERROR", "ERROR"]
    assert [row["module"] for row in rows] == ["STDERR", "STDERR"]
    assert rows[1]["message"] == "UnicodeEncodeError: boom"


def test_tail_initial_success() -> None:
    mock_tail = MagicMock()
    mock_tail.rows = [{"id": "1", "level": "INFO"}]
    mock_tail.file_offsets = {"/tmp/server.log": 100}
    with patch("hirocli.admin.features.logs.service.LogTailTool") as T:
        T.return_value.execute.return_value = mock_tail
        r = LogsService().tail_initial("ws1")
    assert r.ok and r.data is not None
    assert r.data.rows == [{"id": "1", "level": "INFO"}]
    assert r.data.file_offsets == {"/tmp/server.log": 100}
    T.return_value.execute.assert_called_once()
    call_kw = T.return_value.execute.call_args.kwargs
    assert call_kw.get("source") == "all"
    assert call_kw.get("workspace") == "ws1"


def test_tail_initial_tool_error() -> None:
    with patch("hirocli.admin.features.logs.service.LogTailTool") as T:
        T.return_value.execute.side_effect = OSError("denied")
        r = LogsService().tail_initial(None)
    assert not r.ok


def test_tail_after_offsets_runtime_error_returns_empty_snapshot() -> None:
    with patch("hirocli.admin.features.logs.service.LogTailTool") as T:
        T.return_value.execute.side_effect = RuntimeError("rotated")
        r = LogsService().tail_after_offsets("ws", {"a": 1})
    assert r.ok and r.data is not None
    assert r.data.rows == []
    assert r.data.file_offsets == {"a": 1}


def test_search_empty_query() -> None:
    r = LogsService().search("ws", "  ")
    assert not r.ok


def test_search_success() -> None:
    mock_res = MagicMock()
    mock_res.rows = [{"message": "hello"}]
    with patch("hirocli.admin.features.logs.service.LogSearchTool") as T:
        T.return_value.execute.return_value = mock_res
        r = LogsService().search("ws1", "hello")
    assert r.ok and r.data == [{"message": "hello"}]
    T.return_value.execute.assert_called_once()
    assert T.return_value.execute.call_args.kwargs.get("query") == "hello"


def test_search_tool_error() -> None:
    with patch("hirocli.admin.features.logs.service.LogSearchTool") as T:
        T.return_value.execute.side_effect = ValueError("bad")
        r = LogsService().search("ws", "q")
    assert not r.ok


class _GlobFailingPath:
    """Path-like that fails on glob (layout_info error path)."""

    def glob(self, _pattern: str) -> list:
        raise OSError("simulated glob failure")


def test_layout_info_glob_failure() -> None:
    r = LogsService().layout_info(_GlobFailingPath(), None)
    assert not r.ok


def test_tail_after_offsets_success() -> None:
    mock_tail = MagicMock()
    mock_tail.rows = [{"id": "new", "level": "INFO"}]
    mock_tail.file_offsets = {"/tmp/f.log": 999}
    with patch("hirocli.admin.features.logs.service.LogTailTool") as T:
        T.return_value.execute.return_value = mock_tail
        r = LogsService().tail_after_offsets("ws1", {"/tmp/f.log": 100})
    assert r.ok and r.data is not None
    assert r.data.rows == [{"id": "new", "level": "INFO"}]
    assert r.data.file_offsets == {"/tmp/f.log": 999}
    call_kw = T.return_value.execute.call_args.kwargs
    assert call_kw.get("after_offsets") is not None
    assert call_kw.get("workspace") == "ws1"


def test_tail_after_offsets_tool_os_error() -> None:
    with patch("hirocli.admin.features.logs.service.LogTailTool") as T:
        T.return_value.execute.side_effect = OSError("read failed")
        r = LogsService().tail_after_offsets("ws", {"a": 1})
    assert not r.ok


def test_resolve_gateway_log_dir_fallback_success(tmp_path) -> None:
    with patch(
        "hirocli.admin.features.logs.service._resolve_gateway_log_dir",
        return_value=tmp_path,
    ):
        got = LogsService().resolve_gateway_log_dir_fallback()
    assert got == tmp_path


def test_resolve_gateway_log_dir_fallback_swallows() -> None:
    with patch(
        "hirocli.admin.features.logs.service._resolve_gateway_log_dir",
        side_effect=RuntimeError("no registry"),
    ):
        got = LogsService().resolve_gateway_log_dir_fallback()
    assert got is None


def test_pretty_print_log_field_delegates() -> None:
    with patch(
        "hirocli.admin.features.logs.service.pretty_print_log_value",
        return_value=(True, "{\n  \"a\": 1\n}"),
    ) as pp:
        ok, out = LogsService().pretty_print_log_field('{"a": 1}')
    assert ok and "a" in out
    pp.assert_called_once_with('{"a": 1}')
