"""Permissions phase 3, Hiro per person: a turn is its writer's, in a conversation and a memory group of their own; a
stranger's message leaves nothing; a device shows and gets only its own person's conversations."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from hiro_channel_sdk.constants import MESSAGE_TYPE_MESSAGE
from hiro_channel_sdk.models import ContentItem, MessageRouting, UnifiedMessage
from hiro_memory.graph.group_scope import memory_group_id

from hirocli.domain import pairing, people
from hirocli.domain.access import set_rights
from hirocli.domain.conversation_channel import _get_channel_by_id, _list_channels
from hirocli.domain.data_store import chat_user_id, data_db_path, get_default_user_id, person_of_chat_user
from hirocli.domain.db import _give_devices_to_owner, db_path, ensure_db
from hirocli.domain.memory import speaker_name
from hirocli.domain.pairing import ApprovedDevice, upsert_approved_device
from hirocli.domain.people import add_person
from hirocli.domain.talkers import talking_numbers
from hirocli.runtime import agent_manager as am
from hirocli.runtime.chat_writer import PERSON_ID_METADATA_KEY, NotAllowed, writer_of
from hirocli.runtime.device_targeting import DeviceTargeting
from hirocli.runtime.inbound_pipeline import InboundPipeline
from hirocli.runtime.outbound_pipeline import _device_targets
from hirocli.runtime.request_handler import (
    CALLER_DEVICE,
    RequestContext,
    RequestHandler,
    device_asker,
    RequestRefused,
)
from hirocli.runtime.request_methods import DEVICE_RIGHTS, handle_channels_list, handle_messages_history

# The locked map: Adult and Kid talk, and see their own conversations
_ADULT = ["assistant.talk", "conversations.see:own", "conversations.change:own", "memories.see:own"]


class _Bus:
    def publish(self, _event: Any) -> None:
        pass


@pytest.fixture
def family(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """A workspace with the owner (Misho, a number), an Adult who may talk (Mona, a number), a Kid with no grants
    (Mark), and a device for each of Misho and Mona."""
    monkeypatch.setattr(people, "get_domain_event_bus", _Bus)
    monkeypatch.setattr(pairing, "get_domain_event_bus", _Bus)
    misho = add_person(tmp_path, name="Misho", role_ids=["owner"], whatsapp="201000000001")
    mona = add_person(tmp_path, name="Mona", role_ids=["adult"], whatsapp="201000000002")
    mark = add_person(tmp_path, name="Mark", role_ids=["kid"], whatsapp="201000000003")
    set_rights(tmp_path, "adult", "hiroleague", _ADULT)
    get_default_user_id(tmp_path)  # data.db made, with the seeded user and its General
    for device_id, person in (("dev-misho", misho), ("dev-mona", mona)):
        upsert_approved_device(
            tmp_path,
            ApprovedDevice(device_id=device_id, device_public_key="pk", paired_at="2026-11-24T10:00:00Z",
                           person_id=person.person_id),
        )
    return SimpleNamespace(path=tmp_path, misho=misho, mona=mona, mark=mark)


def _whatsapp(number: str, text: str = "hi") -> UnifiedMessage:
    return UnifiedMessage(
        message_type=MESSAGE_TYPE_MESSAGE,
        routing=MessageRouting(channel="whatsapp", direction="inbound", sender_id="1234567890@lid",
                               metadata={"sender_number": number}),
        content=[ContentItem(content_type="text", body=text)],
    )


def _from_device(device_id: str, channel_id: int, text: str = "hi") -> UnifiedMessage:
    return UnifiedMessage(
        message_type=MESSAGE_TYPE_MESSAGE,
        routing=MessageRouting(channel="devices", direction="inbound", sender_id=device_id,
                               metadata={"chat_channel_id": f"server-{channel_id}"}),
        content=[ContentItem(content_type="text", body=text)],
    )


class _Run:
    """The pipeline's two outputs: the ack it emits and the message it hands the agent."""

    def __init__(self) -> None:
        self.emitted: list[UnifiedMessage] = []
        self.ran: list[UnifiedMessage] = []

    async def emit(self, msg: UnifiedMessage) -> None:
        self.emitted.append(msg)

    async def run(self, msg: UnifiedMessage, **_: Any) -> None:
        self.ran.append(msg)


def _ctx(path: Path) -> SimpleNamespace:
    return SimpleNamespace(workspace_path=path, device_names=SimpleNamespace(resolve=lambda device_id: device_id))


def _receive(path: Path, msg: UnifiedMessage, **kw: Any) -> _Run:
    out = _Run()
    pipeline = InboundPipeline(_ctx(path), out.run, out.emit)
    asyncio.run(pipeline.receive(msg.model_dump(mode="json"), **kw))
    return out


def _rows(path: Path, table: str) -> int:
    with sqlite3.connect(str(data_db_path(path))) as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# -- the chat user and the memory group ------------------------------------------------------------------------------


def test_the_owner_keeps_the_seeded_user_and_a_second_person_gets_their_own(family: SimpleNamespace) -> None:
    seeded = get_default_user_id(family.path)
    assert chat_user_id(family.path, family.misho.person_id, owner=True) == seeded
    mona = chat_user_id(family.path, family.mona.person_id, owner=False)
    assert mona != seeded
    assert chat_user_id(family.path, family.mona.person_id, owner=False) == mona  # made once
    assert person_of_chat_user(family.path, seeded) == family.misho.person_id
    # Memory is keyed by the chat user: Mona's turns recall and write her own group, never the owner's
    assert memory_group_id(mona, "hiro") != memory_group_id(seeded, "hiro")


def test_memory_names_each_person_and_the_owner_keeps_the_preference(family: SimpleNamespace) -> None:
    seeded = chat_user_id(family.path, family.misho.person_id, owner=True)
    mona = chat_user_id(family.path, family.mona.person_id, owner=False)
    assert speaker_name(family.path, seeded, "Misho H") == "Misho H"
    assert speaker_name(family.path, mona, "Misho H") == "Mona"


# -- who may write ---------------------------------------------------------------------------------------------------


def test_a_second_person_talks_in_a_conversation_of_their_own(family: SimpleNamespace) -> None:
    out = _receive(family.path, _whatsapp(family.mona.whatsapp))
    assert len(out.ran) == 1
    meta = out.ran[0].routing.metadata
    assert meta[PERSON_ID_METADATA_KEY] == family.mona.person_id
    channel = _get_channel_by_id(family.path, int(meta["chat_channel_id"]))
    assert channel is not None
    assert channel.user_id == chat_user_id(family.path, family.mona.person_id, owner=False)
    assert channel.user_id != get_default_user_id(family.path)


def test_the_owner_on_whatsapp_lands_in_their_general_as_before(family: SimpleNamespace) -> None:
    general = _list_channels(family.path)[0]
    out = _receive(family.path, _whatsapp(family.misho.whatsapp))
    assert int(out.ran[0].routing.metadata["chat_channel_id"]) == general.id


def test_a_strangers_message_leaves_nothing(family: SimpleNamespace) -> None:
    channels, users = _rows(family.path, "channels"), _rows(family.path, "users")
    out = _receive(family.path, _whatsapp("209999999999"))
    assert out.ran == [] and out.emitted == []  # not answered, not even acknowledged
    assert (_rows(family.path, "channels"), _rows(family.path, "users")) == (channels, users)


def test_someone_who_may_not_talk_is_dropped_too(family: SimpleNamespace) -> None:
    out = _receive(family.path, _whatsapp(family.mark.whatsapp))  # Kid: nothing granted in this workspace
    assert out.ran == [] and out.emitted == []


def test_a_device_cant_write_into_another_persons_conversation(family: SimpleNamespace) -> None:
    owners_general = _list_channels(family.path)[0]
    out = _receive(family.path, _from_device("dev-mona", owners_general.id))
    assert out.ran == []
    own = _receive(family.path, _from_device("dev-misho", owners_general.id))
    assert len(own.ran) == 1


def test_the_admin_writes_as_the_signed_in_person_only_in_their_own(family: SimpleNamespace) -> None:
    owners_general = _list_channels(family.path)[0]
    msg = _from_device("admin", owners_general.id)
    with pytest.raises(NotAllowed):
        writer_of(family.path, msg, person_id=family.mark.person_id)  # Mark may not talk
    writer = writer_of(family.path, msg, person_id="")  # the command line: the owner
    assert writer.person_id == family.misho.person_id


def test_with_no_family_list_a_device_is_the_owners(tmp_path: Path) -> None:
    get_default_user_id(tmp_path)
    general = _list_channels(tmp_path)[0]
    out = _receive(tmp_path, _from_device("dev-any", general.id))
    assert len(out.ran) == 1
    assert _receive(tmp_path, _whatsapp("201000000001")).ran == []  # but no stranger on a chat channel


def test_the_numbers_that_may_talk_are_those_of_people_who_may(family: SimpleNamespace) -> None:
    assert talking_numbers(family.path) == sorted([family.misho.whatsapp, family.mona.whatsapp])


# -- devices ---------------------------------------------------------------------------------------------------------


def test_devices_paired_before_phase_3_become_the_owners(family: SimpleNamespace) -> None:
    ensure_db(family.path)
    with sqlite3.connect(str(db_path(family.path))) as conn:
        conn.execute("UPDATE devices SET person_id = ''")
        assert _give_devices_to_owner(conn) == 2
        owners = {r[0] for r in conn.execute("SELECT person_id FROM devices")}
    assert owners == {family.misho.person_id}


def _device_request(path: Path, device_id: str, method: str) -> RequestContext:
    ctx = RequestContext(_ctx(path), _from_device(device_id, 1))
    ctx.asker = device_asker(path, device_id, DEVICE_RIGHTS.get(method, ("", "")))
    return ctx


def test_a_device_lists_only_its_persons_conversations(family: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    _receive(family.path, _whatsapp(family.mona.whatsapp))  # Mona's General
    monkeypatch.setattr("hirocli.domain.server_info.resolve_channel_capabilities", lambda *a, **k: {})
    seen = asyncio.run(handle_channels_list({}, _device_request(family.path, "dev-mona", "channels.list")))
    mona = chat_user_id(family.path, family.mona.person_id, owner=False)
    assert seen["channels"] and {c["user_id"] for c in seen["channels"]} == {mona}


def test_another_persons_history_answers_as_not_found(family: SimpleNamespace) -> None:
    owners_general = _list_channels(family.path)[0]
    ctx = _device_request(family.path, "dev-mona", "messages.history")
    with pytest.raises(RequestRefused) as refused:
        asyncio.run(handle_messages_history({"channel_id": owners_general.id}, ctx))
    assert refused.value.code == "not_found"


def test_a_device_whose_person_lacks_the_right_is_refused(family: SimpleNamespace) -> None:
    set_rights(family.path, "adult", "hiroleague", ["assistant.talk"])  # no conversations.see
    with pytest.raises(RequestRefused) as refused:
        device_asker(family.path, "dev-mona", DEVICE_RIGHTS["channels.list"])
    assert refused.value.code == "not_allowed"
    with pytest.raises(RequestRefused):
        device_asker(family.path, "dev-mona", ("", ""))  # a method with no right: the owner's devices only
    assert device_asker(family.path, "dev-misho", ("", "")).person_id == family.misho.person_id


def test_the_request_handler_answers_a_refused_device_in_words(family: SimpleNamespace) -> None:
    set_rights(family.path, "adult", "hiroleague", ["assistant.talk"])
    handler = RequestHandler(_ctx(family.path))
    handler.register("channels.list", handle_channels_list, device_right=DEVICE_RIGHTS["channels.list"])
    request = UnifiedMessage(
        message_type="request",
        request_id="r-1",
        routing=MessageRouting(channel="devices", direction="inbound", sender_id="dev-mona"),
        content=[ContentItem(content_type="json", body='{"method": "channels.list", "params": {}}')],
    )

    async def emit(_m: UnifiedMessage) -> None:
        pass

    answer = asyncio.run(handler.handle(request, emit_outbound=emit, caller=CALLER_DEVICE))
    assert answer is not None
    assert "not_allowed" in answer.model_dump_json()


def test_a_reply_goes_only_to_its_persons_connected_devices(family: SimpleNamespace) -> None:
    targeting = DeviceTargeting(family.path)
    for device_id in ("dev-misho", "dev-mona"):
        targeting.connected(device_id)
    out = _receive(family.path, _whatsapp(family.mona.whatsapp))
    reply = UnifiedMessage(
        message_type=MESSAGE_TYPE_MESSAGE,
        routing=MessageRouting(channel="devices", direction="outbound", sender_id="server",
                               metadata=dict(out.ran[0].routing.metadata)),
        content=[ContentItem(content_type="text", body="hello")],
    )
    ctx = SimpleNamespace(device_targeting=targeting)
    assert asyncio.run(_device_targets(ctx, reply)) == ["dev-mona"]
    reply.routing.metadata.pop("chat_channel_id")
    assert asyncio.run(_device_targets(ctx, reply)) == []  # no conversation: no device
    reply.routing.recipient_id = "dev-misho"
    assert asyncio.run(_device_targets(ctx, reply)) is None  # it names its device: sent as it is


# -- the turn's story ------------------------------------------------------------------------------------------------


def test_the_turns_story_is_titled_with_its_person(monkeypatch: pytest.MonkeyPatch) -> None:
    named: list[tuple[str, str]] = []
    monkeypatch.setattr(am.story, "named", lambda name, title="", **_: named.append((name, title)))
    manager = am.AgentManager.__new__(am.AgentManager)
    manager._graph = object()
    manager._ctx = SimpleNamespace(workspace_path=Path("."))

    async def inner(_msg: UnifiedMessage, **_: Any) -> None:
        pass

    manager._handle_inner = inner  # type: ignore[method-assign]
    msg = _whatsapp("201000000002", "what's for dinner?")
    msg.routing.metadata["person_name"] = "Mona"
    asyncio.run(manager.handle(msg))
    assert named == [("core.chat_turn", 'Mona: "what\'s for dinner?"')]


def test_a_dropped_message_says_why_once_at_info(family: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    from hirocli.runtime import inbound_pipeline

    lines: list[tuple[str, str, dict[str, Any]]] = []

    class _Log:
        def info(self, text: str, **fields: Any) -> None:
            lines.append(("info", text, fields))

        def warning(self, text: str, **fields: Any) -> None:
            lines.append(("warning", text, fields))

        def error(self, text: str, **fields: Any) -> None:
            lines.append(("error", text, fields))

        def fineinfo(self, text: str, **fields: Any) -> None:
            pass

    monkeypatch.setattr(inbound_pipeline, "log", _Log())
    _receive(family.path, _whatsapp("209999999999"))
    assert [(level, "nobody in the family list" in text) for level, text, _ in lines] == [("info", True)]
    assert lines[0][2]["channel"] == "whatsapp"
