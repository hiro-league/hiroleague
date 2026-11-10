"""Phase 8: an extension's request handler answers a contract's own error code (e.g. sign_in.finish not_linked)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from hiro_channel_sdk.extension import (
    ExtensionClient,
    ExtensionCredentials,
    ExtensionInfo,
    ExtensionRequestError,
    build_request,
    parse_response,
)


def _answer(tmp_path: Path, handler: Any) -> Any:
    client = ExtensionClient("ws://127.0.0.1:1", ExtensionInfo(name="home"), ExtensionCredentials(tmp_path))
    client.register_request("sign_in.finish", handler)
    msg = build_request("sign_in.finish", {}, sender_id="core", direction="outbound", recipient_id="ext")
    return asyncio.run(client._call_handler(msg, "sign_in.finish", {}, "ext"))


def test_a_refusal_keeps_its_code(tmp_path: Path) -> None:
    async def refuse(_params: dict[str, Any]) -> dict[str, Any]:
        raise ExtensionRequestError("not_linked", "Mark's Home Assistant user isn't linked to anyone.")

    with pytest.raises(ExtensionRequestError) as caught:
        parse_response(_answer(tmp_path, refuse))
    assert caught.value.code == "not_linked"
    assert caught.value.message == "Mark's Home Assistant user isn't linked to anyone."


def test_any_other_failure_is_an_internal_error(tmp_path: Path) -> None:
    async def broken(_params: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("boom")

    with pytest.raises(ExtensionRequestError) as caught:
        parse_response(_answer(tmp_path, broken))
    assert caught.value.code == "internal_error"
