"""Phase 7a end to end: an extension's declared AI uses, ai.ask / ai.profiles, and Refresh.

The real extension socket and the SDK's client in a temporary workspace: the uses the
extension declares when it pairs are kept, it asks on the profile picked for "home:<use>"
(a fake chat model answers), the app can't call the AI methods, and Refresh reads changed
uses so the Uses list marks the new and the removed ones.
"""

from __future__ import annotations

import asyncio
import json
import socket
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from hiro_channel_sdk.constants import METHOD_AI_ASK
from hiro_channel_sdk.extension import (
    STATUS_CONNECTED,
    STATUS_NOT_PAIRED,
    ExtensionClient,
    ExtensionCredentials,
    ExtensionInfo,
    ExtensionRequestError,
    ExtensionUse,
    build_request,
)
from hirocli.domain.config import Config
from hirocli.domain.extensions import list_paired_extensions, start_extension_pairing
from hirocli.domain.preferences import WorkspacePreferences
from hirocli.runtime.ai_for_extensions import AI_REQUEST_HANDLERS
from hirocli.runtime.extension_manager import ExtensionManager
from hirocli.runtime.preferences_runtime import WorkspacePreferencesRuntime
from hirocli.runtime.request_handler import CALLER_DEVICE, CALLER_EXTENSION, RequestHandler
from hirocli.services.ai_ask import providers as providers_mod
from hirocli.services.ai_ask import runner as runner_mod
from hirocli.services.ai_ask import use_rows

GEMINI = "google:gemini-3.8-flash"


class _Store:
    def is_configured(self, provider_id: str) -> bool:
        return True

    def get(self, provider_id: str) -> None:
        return None


class _Chat:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def with_structured_output(self, schema: Any, include_raw: bool = False, **kwargs: Any) -> "_Chat":
        return self

    async def ainvoke(self, messages: list[Any]) -> dict[str, Any]:
        self.prompts.append(messages[0].content[-1]["text"])
        raw = AIMessage(content='{"kind": "news"}', usage_metadata={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})
        return {"raw": raw, "parsed": {"kind": "news"}, "parsing_error": None}


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _wait_for(predicate: Any, timeout: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached in time")
        await asyncio.sleep(0.02)


def _core(workspace: Path, port: int) -> tuple[ExtensionManager, RequestHandler, SimpleNamespace]:
    prefs = WorkspacePreferences.model_validate(
        {"ai": {"profiles": {"sites": {"label": "Short texts", "model": GEMINI}}, "uses": {"home:sites": "sites"}}}
    )
    ctx = SimpleNamespace(
        workspace_path=workspace,
        workspace_name="test",
        config=Config(extension_host="127.0.0.1", extension_port=port),
        stop_event=asyncio.Event(),
        preferences=WorkspacePreferencesRuntime(workspace, initial=prefs),
        extension_manager=None,
    )
    handler = RequestHandler(ctx)  # type: ignore[arg-type]
    for name, fn, callers in AI_REQUEST_HANDLERS:
        handler.register(name, fn, callers=callers)
    manager = ExtensionManager(ctx, handler)  # type: ignore[arg-type]
    ctx.extension_manager = manager
    return manager, handler, ctx


def _info(*uses: ExtensionUse) -> ExtensionInfo:
    return ExtensionInfo(name="home", version="1.0.0", uses=list(uses))


ASK = ExtensionUse(id="ask", name="Ask a camera", pictures=4)
SITES = ExtensionUse(id="sites", name="Sorting sites")
WAKE = ExtensionUse(id="wakeword", name="Wake word check", sound=True)


def test_uses_are_kept_asks_answer_and_refresh_marks_new_and_removed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    chat = _Chat()
    monkeypatch.setattr(providers_mod, "build_chat_model_from_tuning", lambda model_id, **kw: chat)
    monkeypatch.setattr(runner_mod, "_credential_store", lambda path: _Store())

    async def scenario() -> None:
        workspace = tmp_path / "ws"
        port = _free_port()
        manager, handler, ctx = _core(workspace, port)
        server = asyncio.create_task(manager.run())
        await _wait_for(lambda: manager.listen_state()["listening"])
        client = ExtensionClient(f"ws://127.0.0.1:{port}", _info(ASK, SITES), ExtensionCredentials(tmp_path / "home"))
        running = asyncio.create_task(client.run())
        await _wait_for(lambda: client.status == STATUS_NOT_PAIRED)
        client.pair(start_extension_pairing(workspace, code_length=6, ttl_seconds=60).code)
        await _wait_for(lambda: client.status == STATUS_CONNECTED)

        # The declared uses are kept with the paired extension ("json" on the wire).
        [paired] = list_paired_extensions(workspace)
        assert [(u["id"], u["pictures"], u["json"]) for u in paired.declared_uses()] == [("ask", 4, True), ("sites", 0, True)]

        # ai.profiles: the profiles and this extension's use → profile map.
        listed = await client.request("ai.profiles")
        assert listed["uses"] == {"sites": "sites"}
        [row] = listed["profiles"]
        assert (row["id"], row["kind"], row["provider"], row["budget_hint"]) == ("sites", "api", "google", "no limit")

        # ai.ask on the use's profile; the answer has the contract's shape.
        answer = await client.request(
            METHOD_AI_ASK, {"use": "sites", "prompt": "Sort example.com", "schema": {"type": "object"}}, timeout=10
        )
        assert json.loads(answer["text"]) == {"kind": "news"}
        assert (answer["profile_id"], answer["tokens"], answer["plan"]) == ("sites", 15, False)
        assert chat.prompts == ["Sort example.com"]
        # A use with no profile picked: no_profile. A bad picture: invalid.
        with pytest.raises(ExtensionRequestError) as err:
            await client.request(METHOD_AI_ASK, {"use": "ask", "prompt": "Anyone there?"})
        assert err.value.code == "no_profile"
        with pytest.raises(ExtensionRequestError) as err:
            await client.request(METHOD_AI_ASK, {"use": "sites", "prompt": "x", "pictures": ["not base64!"]})
        assert err.value.code == "invalid"

        # The app (a device) can't call the AI methods: they look unknown to it.
        device_msg = build_request(METHOD_AI_ASK, {"use": "sites", "prompt": "x"}, sender_id="phone", direction="inbound")
        refused = await handler.handle(device_msg, emit_outbound=_Sink(), caller=CALLER_DEVICE)
        assert refused is not None and json.loads(refused.content[0].body)["error"]["code"] == "method_not_found"

        # Refresh: the extension now declares wakeword and no longer sites.
        client._info = _info(ASK, WAKE)
        info = await manager.refresh_info(paired.extension_id)
        assert [u["id"] for u in info["uses"]] == ["ask", "wakeword"]
        [ext] = use_rows(workspace, ctx.preferences.current)
        status = {u["key"]: u["status"] for u in ext["uses"]}
        assert status == {"home:ask": "ok", "home:wakeword": "new", "home:sites": "removed"}
        assert manager.snapshot()[paired.extension_id]["info"]["uses"][1]["sound"] is True

        await client.stop()
        ctx.stop_event.set()
        await asyncio.wait_for(asyncio.gather(server, running, return_exceptions=True), timeout=5)

    asyncio.run(scenario())


class _Sink:
    def __init__(self) -> None:
        self.sent: list[Any] = []

    async def __call__(self, msg: Any) -> None:
        self.sent.append(msg)


def test_request_methods_are_extensions_only() -> None:
    from hirocli.runtime.request_methods import _REGISTERED_HANDLERS

    callers = {name: who for name, _, who in _REGISTERED_HANDLERS}
    assert callers["ai.ask"] == frozenset({CALLER_EXTENSION})
    assert callers["ai.profiles"] == frozenset({CALLER_EXTENSION})
