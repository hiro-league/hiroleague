"""Smoke tests for shared Result type (no NiceGUI)."""

from __future__ import annotations

from hirocli.admin.shared.result import Result


def test_result_success_and_fail_alias() -> None:
    ok = Result.success(42)
    assert ok.ok and ok.data == 42 and ok.error is None
    bad = Result.fail("nope")
    assert not bad.ok and bad.error == "nope"
