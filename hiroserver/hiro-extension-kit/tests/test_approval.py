"""What an app is approved for (Permissions phase 8): what it asks to do on its own (`Extension.asks`, declared with
the kit's additions for its uses), what the core says it has and what waits (the welcome, `approval.changed`, Settings →
HiroLeague), the core's refusals as the kit's errors in one place (errors.refusal) through every helper that asks the
core, and the contract's check of what an app asks. Against a fake core held to the SDK's table (testing.FakeCore)."""

import asyncio
import dataclasses

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
from hiro_channel_sdk import ExtensionRequestError
from hiro_channel_sdk.approvals import AI_SEARCH, AI_USE, APPS_ASK, PEOPLE_NOTIFY, PEOPLE_SEE, VOICE_SPEAK, Approval
from hiro_channel_sdk.extension import STATUS_CONNECTED
from sqlmodel import Session, select

from hiro_extension_kit import errors, extension, family, hiroleague, hiroleague_api
from hiro_extension_kit.contract import AppContract
from hiro_extension_kit.db import engine
from hiro_extension_kit.errors import NotAllowed, NotApproved, NotSignedIn
from hiro_extension_kit.extension import ask, ext
from hiro_extension_kit.auth.models import CorePerson
from hiro_extension_kit.llm import ai_api, core_ai, profiles, recorder, search
from hiro_extension_kit.llm.models import LlmRequest
from hiro_extension_kit.testing import FakeCore, FakeLink

SAID = "Test isn't approved yet to read the people list: names, WhatsApp numbers, roles. It waits for the owner's yes."


def run(coro):
    return asyncio.run(coro)


def declares(monkeypatch, **changes) -> None:
    monkeypatch.setattr(extension, "_extension", dataclasses.replace(ext(), **changes))


# --- what the app asks ---------------------------------------------------------------------------------------------


def test_an_app_that_declares_no_asks_yet_sends_none_so_the_core_changes_nothing():
    assert ext().asks is None
    assert hiroleague.info_for("http://test.hiro.local").asks is None


def test_its_asks_go_with_those_its_uses_need_each_once(monkeypatch):
    declares(monkeypatch, asks=(ask(PEOPLE_SEE, "Shows who is home"),
                                ask(APPS_ASK, "Plays alerts on the speakers", required=False, to="home"),
                                ask(AI_USE, "Sorts sites with AI")))
    asks = hiroleague.info_for("http://test.hiro.local").asks
    assert [(a.permission, a.to, a.required, a.why) for a in asks or []] == [
        (PEOPLE_SEE, None, True, "Shows who is home"),
        (APPS_ASK, "home", False, "Plays alerts on the speakers"),
        (AI_USE, None, True, "Sorts sites with AI"),  # listed by the app: not added again
        (VOICE_SPEAK, None, True, "Its voice uses: Speak"),
        (AI_SEARCH, None, True, "Its search uses: Embedding, Reranking"),
    ]


def test_an_app_that_asks_nothing_still_asks_what_its_uses_need(monkeypatch):
    declares(monkeypatch, asks=(), uses=(), voice_uses=(), rerank_uses=())
    assert [a.permission for a in hiroleague.info_for("http://test.hiro.local").asks or []] == [AI_SEARCH]
    declares(monkeypatch, embed_uses=())
    assert hiroleague.info_for("http://test.hiro.local").asks == []


def test_the_contract_takes_only_permissions_the_sdk_knows_with_why_and_the_app_asked(monkeypatch):
    contract = AppContract()
    with pytest.raises(pytest.skip.Exception):  # not declared yet: nothing to check
        contract.test_what_it_asks_to_do_on_its_own_is_understood_and_says_why()
    declares(monkeypatch, asks=(ask(PEOPLE_SEE, "Shows who is home"), ask(APPS_ASK, "Speakers", to="home")))
    contract.test_what_it_asks_to_do_on_its_own_is_understood_and_says_why()
    for bad in (ask("people.everything", "All of it"), ask(PEOPLE_NOTIFY, "  "), ask(APPS_ASK, "Speakers")):
        declares(monkeypatch, asks=(bad,))
        with pytest.raises(AssertionError):
            contract.test_what_it_asks_to_do_on_its_own_is_understood_and_says_why()


# --- what it has, and what waits -----------------------------------------------------------------------------------


@pytest.fixture
def link(monkeypatch):
    """The app's own link, with an address set (no default name to claim on connect) and the core's last word reset."""
    link = hiroleague.link
    monkeypatch.setattr(link, "site_url_set", "http://test.hiro.local")
    monkeypatch.setattr(link, "approval", None)
    return link


WIRE = {"approved": [{"permission": "people.see", "subject": ""}, {"permission": "apps.ask", "subject": "home"}],
        "waiting": [{"permission": "ai.search", "subject": ""}, {"permission": "apps.ask", "subject": "net"}]}


def test_the_welcome_says_what_it_is_approved_for(link):
    assert link.approved_for(AI_USE)  # nothing said yet: the core decides
    link._status(STATUS_CONNECTED, {"core": {"name": "HiroLeague"}, "approval": WIRE})
    assert link.approval == Approval.model_validate(WIRE)
    assert link.approved_for(PEOPLE_SEE) and link.approved_for(APPS_ASK, "home")
    assert not link.approved_for(APPS_ASK, "net") and not link.approved_for(AI_SEARCH)
    link._status(STATUS_CONNECTED, {"core": {"name": "HiroLeague"}})  # a core from before approvals: kept as it was
    assert link.approval == Approval.model_validate(WIRE)


def test_the_owners_answer_arrives_as_approval_changed(link, caplog):
    run(link._approval_changed("approval.changed", WIRE))
    with caplog.at_level("INFO", logger="testapp.hiroleague"):
        run(link._approval_changed("approval.changed", {"approved": None, "waiting": []}))  # approved for everything
    assert link.approved_for(AI_SEARCH)
    assert "TestApp is approved for everything" in caplog.text
    run(link._approval_changed("approval.changed", {"approved": "nonsense"}))  # unreadable: the last word stays
    assert link.approval == Approval(approved=None, waiting=[])


def test_the_owners_answer_reads_every_copy_again(link, monkeypatch):
    # A copy the core refused while the app waited (the family list) is read at once, not at the 30-minute round
    again: list[str] = []
    monkeypatch.setattr(link.follower, "all_again", lambda: again.append("all"))
    run(link._approval_changed("approval.changed", WIRE))
    assert again == ["all"]


def test_a_new_pairing_or_another_core_forgets_what_the_last_one_said(link, monkeypatch):
    monkeypatch.setattr(link.client, "pair", lambda code: None)
    monkeypatch.setattr(link.client, "forget", lambda: None)
    monkeypatch.setattr(link.client, "set_url", lambda url: None)
    for act in (lambda: link.pair("123456"), link.forget, lambda: run(link.set_url("ws://127.0.0.1:18099"))):
        link.approval = Approval.model_validate(WIRE)
        monkeypatch.setattr(type(link.client), "url", property(lambda _c: "ws://127.0.0.1:18082"))
        act()
        assert link.approval is None


def test_settings_lists_what_waits_in_words(link):
    app = FastAPI()
    app.include_router(hiroleague_api.router)
    client = TestClient(app)
    assert client.get("/api/hiroleague").json()["waiting"] == []
    link.approval = Approval.model_validate(WIRE)
    assert client.get("/api/hiroleague").json()["waiting"] == [
        {"permission": "ai.search", "subject": "", "words": "use the search models: turn texts into vectors and rank them"},
        {"permission": "apps.ask", "subject": "net", "words": "ask another app for its data"},
    ]


# --- the core's refusals, in one place -----------------------------------------------------------------------------


@pytest.mark.parametrize(("code", "error", "status"), [("not_approved", NotApproved, 403), ("not_allowed", NotAllowed, 403),
                                                       ("sign_in_again", NotSignedIn, 401)])
def test_the_cores_refusals_are_the_kits_errors_in_its_words(code, error, status):
    refused = errors.refusal(ExtensionRequestError(code, SAID))
    assert type(refused) is error and refused.status == status and str(refused) == SAID
    assert errors.refusal(ExtensionRequestError("timeout", "no answer")) is None  # the helper's own mapping says it


def test_the_family_list_not_approved_says_so_and_keeps_the_copy(fake_core):
    fake_core.approved = []
    with pytest.raises(NotApproved, match="isn't approved to read the people list"):
        run(family.sync())


def test_an_ai_question_not_approved_is_never_kept_as_a_failed_try(fake_ai):
    fake_ai.approved = [PEOPLE_SEE]
    with pytest.raises(NotApproved, match="isn't approved to ask AI"):
        run(profiles.ask(None, "sites", "Who?", [], {"type": "object"}))
    with pytest.raises(NotApproved):
        run(profiles.chat("sites", [{"role": "user", "content": "Hi"}]))
    with Session(engine) as s:
        assert s.exec(select(LlmRequest)).all() == []
    assert recorder.active() is False


def test_search_not_approved_says_so(monkeypatch):
    core = FakeCore()
    core.answers["ai.embed"] = {"vectors": []}
    core.approved = [AI_USE]
    monkeypatch.setattr(search, "link", FakeLink(core))
    with pytest.raises(NotApproved, match="isn't approved to use the search models"):
        run(search.embed(["x"]))


def test_an_ai_use_is_picked_for_the_person_signed_in(fake_ai):
    owner = fake_ai.person("Michel", "owner")
    fake_ai.tokens["p1"] = owner["person_id"]
    fake_ai.answers["ai.uses.set"] = {}
    run(core_ai.set_use("sites", "camera", signed_in="p1"))
    assert ("ai.uses.set", {"use": "sites", "profile": "camera"}) in fake_ai.asked
    assert fake_ai.signed_in == [("ai.uses.set", "p1")]
    with pytest.raises(NotSignedIn):
        run(core_ai.set_use("sites", "camera", signed_in="gone"))


def test_someone_is_added_to_the_family_list_for_the_person_signed_in(fake_core):
    owner = fake_core.person("Michel", "owner")
    fake_core.tokens["p1"] = owner["person_id"]
    lea = run(family.add_person("Lea", signed_in="p1", role_ids=["kid"], whatsapp="201001234567"))
    assert (lea.name, lea.role_ids) == ("Lea", ("kid",))
    assert fake_core.asked[-1] == ("people.add", {"name": "Lea", "role_ids": ["kid"], "whatsapp": "201001234567"})
    assert fake_core.signed_in == [("people.add", "p1")]
    with Session(engine) as s:
        assert s.get(CorePerson, lea.id) is not None  # in the copy at once
    with pytest.raises(NotAllowed, match="No app gives or takes the Owner role"):
        run(family.add_person("Sam", signed_in="p1", role_ids=["owner"]))


def test_the_ai_uses_page_picks_for_the_person_signed_in(fake_ai):
    """The route passes the proof the route check kept on request.state (auth/api.py `caller`) to core_ai."""
    owner = fake_ai.person("Michel", "owner")
    fake_ai.tokens["p1"] = owner["person_id"]
    fake_ai.answers["ai.uses.set"] = {}

    async def signed_in(request: Request) -> None:
        request.state.core_token = "p1"  # as the kit's route check keeps it for a signed-in browser

    app = FastAPI(dependencies=[Depends(signed_in)])
    app.include_router(ai_api.router)
    errors.install(app)
    assert TestClient(app).put("/api/ai/uses/sites", json={"profile_id": "camera"}).status_code == 200
    assert fake_ai.signed_in == [("ai.uses.set", "p1")]


def test_a_name_not_approved_yet_is_refused_in_the_cores_words():
    refused = ExtensionRequestError("not_approved", "Test isn't approved to take a name on the network yet.")
    assert type(hiroleague._claim_error(refused)) is NotApproved


def test_asking_another_app_not_approved_is_the_kits_error_and_its_own_no_stays_the_sdks():
    core = FakeCore()
    core.extensions = {"home": {"home.speak": {"ok": True}}, "net": {}}
    core.approved = [(APPS_ASK, "home")]
    link = FakeLink(core)
    assert run(link.ask("home", "home.speak")) == {"ok": True}
    with pytest.raises(NotApproved, match="isn't approved to ask another app"):
        run(hiroleague.ask_app(core, "net", "net.usage"))
    core.approved = None
    with pytest.raises(ExtensionRequestError) as info:  # the asked app's own answer: the app's asks module says it
        run(link.ask("net", "net.usage"))
    assert info.value.code == "not_offered"
