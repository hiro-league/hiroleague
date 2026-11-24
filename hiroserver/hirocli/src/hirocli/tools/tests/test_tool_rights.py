"""Permissions phase 4, Hiro acts as the person: every tool Hiro can run names one core permission, and a turn's tool
calls are held to the rights of the person it talks to.

The contract: an agent tool with no right fails here (at run time it answers the owner only); a right names a declared
core permission; one about people's things says whose the record is. The map is the one Michel locked (Nov 25).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hirocli.domain import conversation_channel, people
from hirocli.domain.access import set_rights
from hirocli.domain.conversation_channel import create_channel
from hirocli.domain.core_features import CORE_BY_ID
from hirocli.domain.data_store import chat_user_id, get_default_user_id
from hirocli.domain.people import add_person
from hirocli.domain.preferences import io as preferences_io
from hirocli.tools import all_tools
from hirocli.tools.conversation import (
    ConversationChannelCreateTool,
    ConversationChannelGetTool,
    ConversationChannelListTool,
    MessageHistoryTool,
)
from hirocli.tools.langchain_adapter import to_langchain
from hirocli.tools.registry import ToolRegistry
from hirocli.tools.rights import (
    BY_RECORD,
    OWNER_ONLY,
    THEIRS,
    Acting,
    ToolRefused,
    acting_as,
    acting_for,
    entry,
    hold,
    may_use,
)

AGENT_TOOLS = [t for t in all_tools() if "agent" in type(t).surfaces]

# The map Michel locked for phase 4: each tool Hiro can run, and the one permission it needs
TALK = "assistant.talk"
LOCKED: dict[str, str] = {
    **dict.fromkeys(["extension_state", "character_list", "policy_get", "describe_image", "transcribe_audio"], TALK),
    "character_get": "assistant.characters.see",
    **dict.fromkeys(["character_create", "character_update", "character_delete"], "assistant.characters.change"),
    **dict.fromkeys(["conversation_channel_list", "conversation_channel_get", "message_history", "files_head"],
                    "conversations.see"),
    **dict.fromkeys(["conversation_channel_create", "conversation_channel_update", "conversation_channel_delete",
                     "conversation_channel_clear_messages"], "conversations.change"),
    "memory_list": "memories.see",
    "memory_clear": "memories.change",
    **dict.fromkeys(["knowledge_graph_export", "knowledge_answer", "knowledge_get_document", "knowledge_job_status",
                     "knowledge_list_categories", "knowledge_list_documents", "knowledge_list_tags",
                     "knowledge_search", "knowledge_scan_folder"], "knowledge.see"),
    **dict.fromkeys(["knowledge_graph_ingest", "knowledge_graph_ingest_batch", "knowledge_create_category",
                     "knowledge_create_tag", "knowledge_delete_document", "knowledge_ingest",
                     "knowledge_reingest_document", "knowledge_update_document_metadata"], "knowledge.change"),
    **dict.fromkeys(["llm_catalog_get_model", "llm_catalog_list_models", "llm_catalog_list_providers",
                     "available_models_list", "provider_list_configured"], "ai.providers.see"),
    "generate_image": "ai.images.run",
    "channel_list": "extensions.see",
    **dict.fromkeys(["channel_enable", "channel_disable"], "extensions.change"),
    "device_list": "devices.see",
    **dict.fromkeys(["log_problems", "log_search", "log_stories", "log_story", "log_tail"], "logs.see"),
    **dict.fromkeys(["workspace_list", "workspace_show"], "server.see"),
    **dict.fromkeys(["people_list", "notify"], OWNER_ONLY.key),
}

# The core's locked map of default grants (phase 2): Adult and Kid talk, and see and change their own conversations
_KID = ["assistant.talk", "conversations.see:own", "conversations.change:own", "memories.see:own"]


# -- the contract ----------------------------------------------------------------------------------------------------


def test_every_tool_hiro_can_run_names_a_right() -> None:
    assert len(AGENT_TOOLS) > 50
    assert [t.name for t in AGENT_TOOLS if type(t).right is None] == []


def test_each_right_is_a_declared_core_permission_and_says_whose_when_it_is_about_people() -> None:
    for t in AGENT_TOOLS:
        right = type(t).right
        assert right is not None
        if right == OWNER_ONLY:
            continue
        feature = CORE_BY_ID.get(right.feature)
        declared = next((r for r in feature.rights if r.id == right.action), None) if feature else None
        assert declared is not None, f"{t.name}: {right.key} isn't a core permission"
        assert bool(right.whose) == declared.personal, f"{t.name}: whose a record is, for {right.key}"
        if right.whose == BY_RECORD:
            assert callable(getattr(t, "record_users", None)), t.name
        if right.whose == THEIRS:
            assert "acting" in inspect.signature(entry(t)).parameters, t.name


def test_the_map_is_the_one_michel_locked() -> None:
    assert {t.name: type(t).right.key for t in AGENT_TOOLS} == LOCKED  # type: ignore[union-attr]


def test_hiro_is_never_offered_a_workspace_to_work_in() -> None:
    for t in AGENT_TOOLS:
        assert "workspace" not in to_langchain(t).args, t.name


# -- a family ----------------------------------------------------------------------------------------------------------


class _Bus:
    def publish(self, _event: Any) -> None:
        pass


@pytest.fixture
def family(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """The owner (Misho, the seeded chat user) and a Kid (Mark) with the locked map's grants, each with a
    conversation of their own."""
    # No bus runs in a test: without these, each new person, conversation and the first preferences save log "Domain
    # event dropped", and the deploy's check on Simone writes those warnings into live's log store
    for module in (people, conversation_channel, preferences_io):
        monkeypatch.setattr(module, "get_domain_event_bus", _Bus)
    misho = add_person(tmp_path, name="Misho", role_ids=["owner"])
    mark = add_person(tmp_path, name="Mark", role_ids=["kid"])
    set_rights(tmp_path, "kid", "hiroleague", _KID)
    owner_user = get_default_user_id(tmp_path)
    mark_user = chat_user_id(tmp_path, mark.person_id, owner=False)
    owners = create_channel(tmp_path, name="Plans", character_id="hiro", user_id=owner_user)
    marks = create_channel(tmp_path, name="Homework", character_id="hiro", user_id=mark_user)

    def acting(person: Any, user_id: int, owner: bool) -> Acting:
        return acting_for(tmp_path, person_id=person.person_id, name=person.name, user_id=user_id, owner=owner)

    return SimpleNamespace(
        path=tmp_path, misho=acting(misho, owner_user, True), mark=acting(mark, mark_user, False),
        owners=owners, marks=marks,
    )


def test_the_family_logs_no_warning(family: SimpleNamespace, caplog: pytest.LogCaptureFixture) -> None:
    """The fixture's people and conversations leave no warning behind (the deploy's check runs these on Simone)."""
    caplog.set_level(logging.WARNING, logger="DOMAIN.BUS")
    create_channel(family.path, name="Another", character_id="hiro", user_id=family.mark.user_id)
    ConversationChannelListTool().execute(workspace_path=family.path)  # its first read saves the preferences
    assert [r for r in caplog.records if r.name == "DOMAIN.BUS"] == []


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register_all(all_tools())
    return registry


# -- what a person's turn is offered ---------------------------------------------------------------------------------


def test_a_kids_turn_is_offered_talking_and_their_own_conversations_only(family: SimpleNamespace) -> None:
    from hirocli.runtime.agent_manager import tools_offered

    registry = _registry()
    kid = set(tools_offered(registry, family.mark, tools_enabled=True))
    assert kid == {
        "extension_state", "character_list", "policy_get", "describe_image", "transcribe_audio",
        "conversation_channel_list", "conversation_channel_get", "message_history", "files_head",
        "conversation_channel_create", "conversation_channel_update",
    }
    owner = set(tools_offered(registry, family.misho, tools_enabled=True))
    assert owner == {t.name for t in registry.agent_tools()}  # nothing changes for the owner


def test_with_tools_off_a_turn_keeps_only_the_always_on_ones_it_may_use(family: SimpleNamespace) -> None:
    from hirocli.runtime.agent_manager import tools_offered

    registry = _registry()
    assert tools_offered(registry, family.mark, tools_enabled=False) == ["extension_state"]
    nobody = Acting(person_id="p-x", name="Joe", user_id=9, owner=False, workspace_path=family.path)
    assert tools_offered(registry, nobody, tools_enabled=False) == []  # no talk, so not even the home


def test_hiros_knowledge_recall_needs_knowledge_see(family: SimpleNamespace) -> None:
    from hirocli.runtime.agent_manager import KNOWLEDGE_SEE

    assert family.mark.reach(KNOWLEDGE_SEE) == "no"
    assert family.misho.reach(KNOWLEDGE_SEE) == "all"


# -- the hold on each call ---------------------------------------------------------------------------------------------


def test_a_tool_the_person_may_not_use_is_refused_with_words(family: SimpleNamespace) -> None:
    logs = next(t for t in AGENT_TOOLS if t.name == "log_tail")
    people_list = next(t for t in AGENT_TOOLS if t.name == "people_list")
    with acting_as(family.mark):
        with pytest.raises(ToolRefused) as refused:
            hold(logs, {})
        assert refused.value.reason == "no_right" and "logs.see" in refused.value.words
        with pytest.raises(ToolRefused) as refused:
            hold(people_list, {})
        assert "only the owner" in refused.value.words
    assert not may_use(family.mark, people_list) and may_use(family.misho, people_list)


def test_a_turn_with_no_person_runs_no_tool() -> None:
    with pytest.raises(ToolRefused) as refused:
        hold(ConversationChannelListTool(), {})
    assert refused.value.reason == "nobody"


def test_hiro_works_in_the_turns_workspace_whatever_the_model_names(family: SimpleNamespace) -> None:
    with acting_as(family.misho):
        held = hold(ConversationChannelListTool(), {"workspace": "someone-elses"})
    assert held["workspace_path"] == family.path and "workspace" not in held


def test_a_kid_lists_and_reads_their_own_conversations_only(family: SimpleNamespace) -> None:
    listing = ConversationChannelListTool()
    with acting_as(family.mark):
        mine = listing.execute(**hold(listing, {})).channels
        assert {c["id"] for c in mine} >= {family.marks.id} and family.owners.id not in {c["id"] for c in mine}
        history = MessageHistoryTool()
        history.execute(**hold(history, {"channel_id": family.marks.id}))
        with pytest.raises(ToolRefused) as refused:
            hold(history, {"channel_id": family.owners.id})  # the owner's: as if it didn't exist
        assert refused.value.reason == "not_theirs"
        get = ConversationChannelGetTool()
        assert get.execute(**hold(get, {"channel_id": family.owners.id})).channel is None
        assert get.execute(**hold(get, {"channel_id": family.marks.id})).channel["id"] == family.marks.id
    with acting_as(family.misho):  # the owner reaches everyone's, as today
        everyone = listing.execute(**hold(listing, {})).channels
        assert {family.owners.id, family.marks.id} <= {c["id"] for c in everyone}
        history.execute(**hold(history, {"channel_id": family.marks.id}))


def test_a_new_conversation_is_the_persons_own(family: SimpleNamespace) -> None:
    create = ConversationChannelCreateTool()
    with acting_as(family.mark):
        made = create.execute(**hold(create, {"channel_name": "Science", "character_id": "hiro"})).channel
    assert made["user_id"] == family.mark.user_id
    assert create.execute(channel_name="Owner's", character_id="hiro", workspace_path=family.path).channel[
        "user_id"] == family.misho.user_id  # the command line and the admin: the owner, as before


# -- through Hiro's own path: the adapter and the tools node ----------------------------------------------------------


def test_a_sync_tool_sees_the_turns_person_through_langchain(family: SimpleNamespace) -> None:
    """LangChain runs a sync tool in a thread: the person must reach it there."""
    tool = to_langchain(ConversationChannelListTool())

    async def run() -> Any:
        with acting_as(family.mark):
            return await tool.ainvoke({})

    ids = {c["id"] for c in asyncio.run(run()).channels}
    assert family.marks.id in ids and family.owners.id not in ids


def _tools_node(tools: list[Any]) -> Any:
    from hirocli.runtime.agent_graph.config import ChatGraphConfig
    from hirocli.runtime.agent_graph.nodes.llm import LLMNodes

    class _Model:
        def bind_tools(self, chosen: Any, **_: Any) -> Any:
            return SimpleNamespace(tools=tuple(t.name for t in chosen))

    config = ChatGraphConfig(model=_Model(), tools=tools, model_id="fake:m", system_prompt=None)  # type: ignore[arg-type]
    return LLMNodes(services=SimpleNamespace(preferences=None, workspace_path=None), config=config)  # type: ignore[arg-type]


def _call(nodes: Any, name: str, args: dict[str, Any], offered: list[str]) -> Any:
    from langchain_core.messages import AIMessage

    state = {"messages": [AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "c1"}])],
             "tools_offered": offered}
    return asyncio.run(nodes.tools_node(state, lambda *_: None))["messages"][0]


def test_the_model_is_bound_to_the_offered_tools_only(family: SimpleNamespace) -> None:
    nodes = _tools_node([to_langchain(t) for t in AGENT_TOOLS])
    assert set(nodes.bound_for(["extension_state", "log_tail"]).tools) == {"extension_state", "log_tail"}
    assert nodes.bound_for([]) is nodes._model


def test_a_refused_call_reaches_the_model_as_words_and_logs_one_line(
    family: SimpleNamespace, caplog: pytest.LogCaptureFixture
) -> None:
    nodes = _tools_node([to_langchain(t) for t in AGENT_TOOLS])
    caplog.set_level(logging.INFO, logger="AGENT.GRAPH")
    with acting_as(family.mark):
        not_theirs = _call(nodes, "message_history", {"channel_id": family.owners.id}, ["message_history"])
        not_offered = _call(nodes, "log_tail", {}, ["message_history"])
        offered_but_held = _call(nodes, "log_tail", {}, ["log_tail"])  # a wrong offer is still held at the call
    assert not_theirs.content.startswith("Not allowed:") and "no such record" in not_theirs.content
    assert "isn't one of the tools" in not_offered.content
    assert "logs.see" in offered_but_held.content
    refused = [r for r in caplog.records if "Tool refused" in r.getMessage()]
    assert len(refused) == 3 and all(r.levelno == logging.INFO for r in refused)
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING and "tool" in r.getMessage().lower()]


def test_a_kids_ask_to_the_home_is_for_the_kid(family: SimpleNamespace) -> None:
    """Done when: a kid asking who is home gets a kid's answer. The always-on tool asks the app for the turn's
    person, and the app answers by that person's rights."""
    from hiro_channel_sdk.constants import FOR_PERSON

    from hirocli.services.ai_usage.from_ledger import usage_person
    from hirocli.tools.extension_state import _for_whom

    token = usage_person.set(family.mark.person_id)
    try:
        assert _for_whom() == {FOR_PERSON: family.mark.person_id}
    finally:
        usage_person.reset(token)
    assert may_use(family.mark, next(t for t in AGENT_TOOLS if t.name == "extension_state"))


# -- a whole turn through the compiled chat graph -----------------------------------------------------------------------


async def _turn_listing(family: SimpleNamespace, acting: Acting | None) -> dict[str, Any]:
    """One turn of the real compiled graph, its model scripted to list conversations, run as the agent manager runs
    it: the person set around the run, never inside it. Returns the tool's event payload."""
    from hiro_memory.testing import ai_text, ai_tool_call

    from hirocli.runtime.agent_graph.events import GRAPH_TOOL_COMPLETED
    from hirocli.runtime.tests.graph_fakes import FakeMemory, make_inbound_envelope, run_graph
    from hirocli.runtime.tests.test_chat_graph_characterization import _build_chat, _state
    from hirocli.tools.rights import begin, end

    compiled, _sink, _ = _build_chat(
        family.path,
        responses=[ai_tool_call("conversation_channel_list", {}), ai_text("done")],
        tools=(to_langchain(ConversationChannelListTool()),),
        memory=FakeMemory(),
    )
    state = _state(family.path, make_inbound_envelope(text="which chats do I have?"),
                   tools_offered=["conversation_channel_list"],
                   data_user_id=acting.user_id if acting else family.mark.user_id)
    token = begin(acting) if acting is not None else None
    try:
        result = await run_graph(compiled, state)
    finally:
        if token is not None:
            end(token)
    payload = result.event_payload(GRAPH_TOOL_COMPLETED)
    assert payload is not None
    return payload


@pytest.mark.asyncio
async def test_through_the_compiled_graph_a_kids_hiro_lists_only_the_kids_conversations(
    family: SimpleNamespace,
) -> None:
    payload = await _turn_listing(family, family.mark)
    assert payload["status"] == "completed"
    assert "Homework" in payload["result"] and "Plans" not in payload["result"]


@pytest.mark.asyncio
async def test_through_the_compiled_graph_a_turn_with_no_person_runs_no_tool(family: SimpleNamespace) -> None:
    payload = await _turn_listing(family, None)
    assert payload["status"] == "refused" and "whom this turn is for" in payload["error"]


def test_a_kid_gets_no_file_from_another_persons_conversation(family: SimpleNamespace, monkeypatch: pytest.MonkeyPatch) -> None:
    """files_head, offered to a Kid, keeps to their own conversations: the owner's attachment answers as missing."""
    from hirocli.domain import files_resolver
    from hirocli.tools.files import FilesHeadTool

    seen: list[int | None] = []

    def lookup(_path: Path, *, message_external_id: str, slot_index: int, user_id: int | None) -> None:
        seen.append(user_id)  # the chat user the attachment must belong to; none of this test's rows match
        return None

    monkeypatch.setattr(files_resolver, "get_attachment_by_message_external_id", lookup)
    tool = FilesHeadTool()
    with acting_as(family.mark), pytest.raises(FileNotFoundError):
        tool.execute(**hold(tool, {"ref": "message_attachment:owners-msg:0"}))
    with acting_as(family.misho), pytest.raises(FileNotFoundError):
        tool.execute(**hold(tool, {"ref": "message_attachment:owners-msg:0"}))
    assert seen == [family.mark.user_id, None]  # the Kid's own only; the owner reaches everyone's, as before


def test_a_tool_that_takes_only_a_workspace_name_gets_hiros_own(
    family: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    from hirocli.domain import workspace as workspace_mod
    from hirocli.tools import rights

    registry = SimpleNamespace(workspaces={"ws-hiro": SimpleNamespace(path=str(family.path)),
                                           "ws-other": SimpleNamespace(path=str(family.path / "other"))})
    monkeypatch.setattr(workspace_mod, "load_registry", lambda: registry)
    assert rights.workspace_id_of(family.path) == "ws-hiro"
    named_only = next(t for t in AGENT_TOOLS if t.name == "log_tail")
    assert "workspace_path" not in inspect.signature(entry(named_only)).parameters
    owner = Acting(person_id=family.misho.person_id, name="Misho", user_id=family.misho.user_id, owner=True,
                   workspace_path=family.path, workspace_id=rights.workspace_id_of(family.path))
    with acting_as(owner):
        assert hold(named_only, {"workspace": "ws-other"})["workspace"] == "ws-hiro"
