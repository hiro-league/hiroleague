"""Phase 5: notify (Hiro tells people something) and the extension_state agent tool.

notify against a fake ChannelManager and agent: exact text goes as given, style
"character" goes as the character wrote it, the owner's copy lands in the owner's
conversation and Hiro's thread, and one person failing doesn't stop the others.
extension_state against a fake ExtensionManager.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hiro_channel_sdk import ExtensionRequestError
from hirocli.domain.channel_config import ChannelConfig, save_channel_config
from hirocli.domain.conversation_channel import resolve_default_channel
from hirocli.domain.message_store import list_messages
from hirocli.runtime.channel_manager import ChannelCallError
from hirocli.runtime.notify import handle_notify
from hirocli.runtime.request_handler import RequestRefused
from hirocli.tools.extension_state import ExtensionStateTool

OWNER = "201001234569"
SARA = "201112223334"


class FakeChannels:
    def __init__(self, fail_for: set[str] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail_for = fail_for or set()

    async def call_channel(self, channel: str, name: str, params: dict[str, Any], *, timeout: float) -> Any:
        assert (channel, name) == ("whatsapp", "send")
        self.calls.append(params)
        if params["to"] in self.fail_for:
            raise ChannelCallError("WhatsApp refused the number", "whatsapp_failed")
        return {"sent": True}


class FakeAgent:
    def __init__(self, fail: bool = False) -> None:
        self.added: list[str] = []
        self.asked: list[tuple[int | None, str]] = []
        self.fail = fail

    async def add_sent_message(self, chat_channel_id: int, text: str) -> bool:
        self.added.append(text)
        return True

    async def write_as_character(self, chat_channel_id: int | None, instruction: str) -> tuple[str, str]:
        self.asked.append((chat_channel_id, instruction))
        if self.fail:
            raise RuntimeError("no chat model set")
        return "Hey! Joe's home safe 🙂", "Hiro"


def _ctx(workspace: Path, channels: FakeChannels | None, agent: FakeAgent | None = None) -> SimpleNamespace:
    server_ctx = SimpleNamespace(workspace_path=workspace, channel_manager=channels, agent_manager=agent,
                                 extension_manager=None, channel_status={})
    return SimpleNamespace(server_ctx=server_ctx, msg=SimpleNamespace(routing=SimpleNamespace(sender_id="ext-home")),
                           workspace_path=workspace)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    save_channel_config(tmp_path, ChannelConfig(name="whatsapp", config={"owner_number": f"+{OWNER}"}))
    return tmp_path


def _bodies(workspace: Path) -> list[str]:
    rows = asyncio.run(list_messages(workspace, int(resolve_default_channel(workspace).id)))
    return [row["body"] for row in rows]


def _params(style: str = "exact", *people: tuple[str, str]) -> dict[str, Any]:
    to = [{"name": n, "number": num} for n, num in (people or (("Sara", SARA),))]
    return {"to": to, "medium": "whatsapp", "text": "Joe just got home", "style": style}


def test_exact_goes_as_given_and_only_the_owners_copy_is_kept(workspace: Path) -> None:
    channels, agent = FakeChannels(), FakeAgent()
    params = _params("exact", ("Sara", SARA), ("Michel", f"+{OWNER}"))
    answer = asyncio.run(handle_notify(params, _ctx(workspace, channels, agent)))
    assert [c["text"] for c in channels.calls] == ["Joe just got home", "Joe just got home"]
    assert [c["to"] for c in channels.calls] == [SARA, OWNER]
    assert [r["sent"] for r in answer["results"]] == [True, True]
    assert agent.asked == []
    assert _bodies(workspace) == ["Joe just got home"]
    assert agent.added == ["Joe just got home"]


def test_character_writes_it_in_the_owners_conversation_character(workspace: Path) -> None:
    channels, agent = FakeChannels(), FakeAgent()
    asyncio.run(handle_notify(_params("character", ("Michel", OWNER)), _ctx(workspace, channels, agent)))
    channel_id, instruction = agent.asked[0]
    assert channel_id == int(resolve_default_channel(workspace).id)
    assert "Joe just got home" in instruction and "Michel" in instruction
    assert channels.calls[0]["text"] == "Hey! Joe's home safe 🙂"
    assert _bodies(workspace) == ["Hey! Joe's home safe 🙂"]


def test_someone_without_a_conversation_gets_the_default_character(workspace: Path) -> None:
    agent = FakeAgent()
    asyncio.run(handle_notify(_params("character"), _ctx(workspace, FakeChannels(), agent)))
    assert agent.asked[0][0] is None


def test_one_failing_doesnt_stop_the_others(workspace: Path) -> None:
    channels = FakeChannels(fail_for={SARA})
    answer = asyncio.run(handle_notify(_params("exact", ("Sara", SARA), ("Michel", OWNER)), _ctx(workspace, channels, FakeAgent())))
    sara, michel = answer["results"]
    assert sara["sent"] is False and "refused" in sara["error"]
    assert michel["sent"] is True


def test_the_character_failing_is_a_failed_send_not_a_crash(workspace: Path) -> None:
    channels = FakeChannels()
    answer = asyncio.run(handle_notify(_params("character"), _ctx(workspace, channels, FakeAgent(fail=True))))
    assert answer["results"][0]["sent"] is False
    assert "couldn't write" in answer["results"][0]["error"]
    assert channels.calls == []


def test_whatsapp_not_running_is_said_per_person(workspace: Path) -> None:
    answer = asyncio.run(handle_notify(_params(), _ctx(workspace, None, FakeAgent())))
    assert answer["results"][0] == {"name": "Sara", "number": SARA, "sent": False, "error": "WhatsApp isn't running in HiroLeague"}


@pytest.mark.parametrize(
    "params",
    [
        {"to": [], "text": "x"},
        {"to": [{"name": "Sara"}], "text": "x"},
        {"to": [{"name": "Sara", "number": SARA}], "text": "  "},
        {"to": [{"name": "Sara", "number": SARA}], "text": "x", "style": "loud"},
        {"to": [{"name": "Sara", "number": SARA}], "text": "x", "medium": "sms"},
        {"to": [{"name": str(i), "number": SARA} for i in range(11)], "text": "x"},
    ],
)
def test_bad_requests_are_refused_before_anything_is_sent(workspace: Path, params: dict[str, Any]) -> None:
    channels = FakeChannels()
    with pytest.raises(RequestRefused) as refused:
        asyncio.run(handle_notify(params, _ctx(workspace, channels, FakeAgent())))
    assert refused.value.code == "invalid_params"
    assert channels.calls == []


# --- extension_state -------------------------------------------------------------------------------


class FakeExtensions:
    def __init__(self, live: dict[str, dict[str, Any]], fail: set[str] | None = None) -> None:
        self.live, self.fail, self.asked = live, fail or set(), []

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return self.live

    async def request(self, extension_id: str, method: str, params: Any = None, *, timeout: float) -> dict[str, Any]:
        self.asked.append((extension_id, method))
        if extension_id in self.fail:
            raise ExtensionRequestError("timeout", "no answer to extension.state in 15s")
        return {"state": {"people": [{"name": "Joe", "presence": "home", "room": "Kitchen"}]}}


def _tool(extensions: FakeExtensions | None) -> ExtensionStateTool:
    tool = ExtensionStateTool()
    tool.attach_runtime(SimpleNamespace(comm_manager=SimpleNamespace(ctx=SimpleNamespace(extension_manager=extensions))))
    return tool


HOME = {"name": "home", "info": {"description": "HomeHiro"}}


def test_extension_state_hands_each_extensions_state_over_as_it_is() -> None:
    extensions = FakeExtensions({"ext-1": HOME})
    result = asyncio.run(_tool(extensions).execute_async())
    assert extensions.asked == [("ext-1", "extension.state")]
    assert result.extensions == [{"extension": "home", "description": "HomeHiro",
                                  "state": {"people": [{"name": "Joe", "presence": "home", "room": "Kitchen"}]}}]


def test_extension_state_says_when_nothing_answers() -> None:
    assert asyncio.run(_tool(FakeExtensions({})).execute_async()).note == "No extension is connected now"
    assert "named 'garden'" in asyncio.run(_tool(FakeExtensions({"ext-1": HOME})).execute_async("garden")).note
    failed = asyncio.run(_tool(FakeExtensions({"ext-1": HOME}, fail={"ext-1"})).execute_async())
    assert failed.extensions == [{"extension": "home", "error": "home didn't answer: no answer to extension.state in 15s"}]
