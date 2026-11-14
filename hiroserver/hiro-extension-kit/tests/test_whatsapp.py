"""WhatsApp through the HiroLeague core (whatsapp.py): what is asked of the core, OUTPUTS=off, every failure
in words (and whether the message may have gone out), and the core's status as the app shows it. The core
is faked at its request (`link.client.request`), so nothing is sent.

Shared-code plan, step 1: HomeHiro's and NetHiro's tests each had this file; it is tested once, here. HomeHiro's
own pages (a person's number, the test message) stay in its tests."""

import asyncio
import base64
import logging
from typing import Any

import pytest
from hiro_channel_sdk import ExtensionRequestError
from hiro_channel_sdk.constants import (
    METHOD_WHATSAPP_CHECK,
    METHOD_WHATSAPP_SEND,
    METHOD_WHATSAPP_STATUS,
    WHATSAPP_ERROR_FAILED,
    WHATSAPP_ERROR_NOT_CONNECTED,
    WHATSAPP_ERROR_NOT_RUNNING,
)

from hiro_extension_kit import errors, testing, whatsapp


class FakeClient:
    """The SDK's ExtensionClient as whatsapp.py uses it: `connected`, and `request()` answering from `answer`."""

    def __init__(self) -> None:
        self.connected = True
        self.asked: list[tuple[str, dict[str, Any], float]] = []
        self.answer: Any = {"sent": True}  # a dict, or an exception to raise

    async def request(self, method: str, params: dict[str, Any] | None = None, *, timeout: float = 15.0) -> dict[str, Any]:
        self.asked.append((method, params or {}, timeout))
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer


class FakeLink:
    def __init__(self) -> None:
        self.client = FakeClient()


@pytest.fixture
def core(monkeypatch) -> FakeClient:
    link = FakeLink()
    monkeypatch.setattr(whatsapp, "link", link)
    testing.outputs(monkeypatch, True)  # the fake core sends nothing
    return link.client


def run(coro):
    return asyncio.run(coro)


# --- sending ---------------------------------------------------------------------------------------------


def test_outputs_off_logs_and_asks_nothing(core, monkeypatch, caplog):
    testing.outputs(monkeypatch, False)
    with caplog.at_level(logging.INFO, "testapp.whatsapp"):
        assert run(whatsapp.send("201001234567", "hello")) is False
    assert core.asked == []
    assert [r.getMessage() for r in caplog.records] == ["OUTPUTS=off, not sending WhatsApp to 201001234567: hello"]


def test_not_connected_to_hiroleague_sends_nothing_and_says_so(core):
    core.connected = False
    with pytest.raises(whatsapp.WhatsAppNotRunning) as info:
        run(whatsapp.send("201001234567", "hello"))
    assert str(info.value) == "TestApp isn't connected to HiroLeague (Settings → HiroLeague)"
    assert info.value.status == 502 and core.asked == []


@pytest.mark.parametrize(("code", "kind", "says"), [
    (WHATSAPP_ERROR_NOT_RUNNING, whatsapp.WhatsAppNotRunning, "HiroLeague's WhatsApp isn't running (HiroLeague's admin, Channels → WhatsApp)"),
    (WHATSAPP_ERROR_NOT_CONNECTED, whatsapp.WhatsAppNotRunning,
     "WhatsApp isn't linked or online in HiroLeague (HiroLeague's admin, Channels → WhatsApp)"),
    (WHATSAPP_ERROR_FAILED, whatsapp.WhatsAppError, "WhatsApp failed: the number refused it"),
    ("invalid_params", whatsapp.WhatsAppError, "HiroLeague refused the request: the number refused it"),
    ("internal_error", whatsapp.WhatsAppError, "HiroLeague failed (internal_error): the number refused it"),
])
def test_the_cores_errors_in_words(core, code, kind, says):
    core.answer = ExtensionRequestError(code, "the number refused it")
    with pytest.raises(whatsapp.WhatsAppError) as info:
        run(whatsapp.send("201001234567", "hello"))
    assert type(info.value) is kind and str(info.value) == says and info.value.status == 502


def test_a_send_that_may_have_gone_out_is_never_not_running(core):
    """A timeout, or the connection dropping after the request left: the message may be out. "Not running"
    would invite a second send."""
    for answer, says in [(ExtensionRequestError("timeout", "no answer in 60s"),
                          "HiroLeague didn't answer in 60 s; it may have gone out already (check before sending again)"),
                         (ExtensionRequestError("not_connected", "connection closed"),
                          "The connection to HiroLeague dropped; it may have gone out already (check before sending again)"),
                         ({"sent": False}, "HiroLeague answered without saying the message was sent (check before sending again)")]:
        core.answer = answer
        with pytest.raises(whatsapp.WhatsAppError) as info:
            run(whatsapp.send("201001234567", "hello"))
        assert not isinstance(info.value, whatsapp.WhatsAppNotRunning) and str(info.value) == says


def test_text_image_and_voice_go_to_the_core_as_its_send_asks(core):
    assert run(whatsapp.send("201001234567", "hello")) is True
    assert run(whatsapp.send("201001234567", "the door", image=b"\xff\xd8jpeg")) is True
    assert run(whatsapp.send("201001234567", voice=b"OggS", voice_seconds=2.5, waveform=bytes(range(64)))) is True
    (m1, text, t1), (m2, image, _), (m3, voice, _) = core.asked
    assert m1 == m2 == m3 == METHOD_WHATSAPP_SEND and t1 == whatsapp.SEND_TIMEOUT == 60
    assert text == {"to": "201001234567", "text": "hello"}
    assert image == {"to": "201001234567", "text": "the door", "image_b64": base64.b64encode(b"\xff\xd8jpeg").decode()}
    assert voice == {"to": "201001234567", "voice_b64": base64.b64encode(b"OggS").decode(), "voice_seconds": 2.5,
                     "waveform_b64": base64.b64encode(bytes(range(64))).decode()}


def test_notify_names_the_person_by_their_id_in_hiroleague(core):
    core.answer = {"results": [{"person": "cp1", "name": "Yoyo", "sent": True}]}
    assert run(whatsapp.notify("cp1", "Youssef", "dinner", character=True)) is True
    method, params, _ = core.asked[-1]
    assert params == {"to": [{"person": "cp1"}], "medium": "whatsapp", "text": "dinner", "style": "character"}
    core.answer = {"results": [{"person": "cp1", "name": "Yoyo", "sent": False, "error": "Yoyo has no WhatsApp number"}]}
    with pytest.raises(whatsapp.WhatsAppError, match="Hiro didn't send it: Yoyo has no WhatsApp number"):
        run(whatsapp.notify("cp1", "Youssef", "dinner", character=False))


def test_check_asks_the_core_and_reads_its_answers(core):
    core.answer = {"answers": [{"query": "201001234567", "on_whatsapp": True, "jid": "201001234567@s.whatsapp.net"}]}
    assert run(whatsapp.check(["201001234567"])) == [
        {"query": "201001234567", "on_whatsapp": True, "jid": "201001234567@s.whatsapp.net"}]
    assert core.asked == [(METHOD_WHATSAPP_CHECK, {"numbers": ["201001234567"]}, 30)]
    core.answer = {"answers": [{"query": "2010"}]}  # no on_whatsapp
    with pytest.raises(whatsapp.WhatsAppError, match="check can't be read"):
        run(whatsapp.check(["2010"]))
    with pytest.raises(errors.Invalid, match="At most 20"):
        run(whatsapp.check([str(n) for n in range(21)]))


def test_a_dropped_connection_while_checking_is_not_connected(core):
    core.answer = ExtensionRequestError("not_connected", "connection closed")  # nothing is sent by a check
    with pytest.raises(whatsapp.WhatsAppNotRunning, match="isn't connected to HiroLeague"):
        run(whatsapp.check(["201001234567"]))


def test_a_number_without_country_code_is_invalid():
    with pytest.raises(errors.Invalid, match="international format") as info:
        whatsapp.normalize_number("0100 123 4567")
    assert info.value.status == 400
    with pytest.raises(errors.Invalid, match="full phone number"):
        whatsapp.normalize_number("+20 1")


# --- the status ------------------------------------------------------------------------------------------


def status_of(core: FakeClient, **answer: Any) -> whatsapp.WhatsAppStatus:
    core.answer = {"running": True, "state": "", "detail": {}, "waiting_for_link": False, "account": "", **answer}
    return run(whatsapp.status())


def test_the_cores_status_as_the_app_shows_it(core):
    s = status_of(core, state="connected", account="201001234567")
    assert (s.state, s.account, s.note, s.outputs) == ("connected", "201001234567", None, True)
    assert core.asked[-1] == (METHOD_WHATSAPP_STATUS, {}, 10)
    assert (status_of(core, running=False, state="connected").state) == "not_running"  # not running wins
    assert status_of(core, waiting_for_link=True).note == "Waiting to be linked: scan the QR code in HiroLeague's admin, Channels → WhatsApp"
    assert (status_of(core, state="paired", account="2010").state, status_of(core).state) == ("connecting", "starting")
    s = status_of(core, state="error", detail={"reason": "client_outdated"})
    assert (s.state, s.note) == ("error", "WhatsApp failed: client_outdated")
    assert status_of(core, state="replaced").note == "Another program took over the WhatsApp link"
    assert (status_of(core, state="sleeping").state, status_of(core, state="sleeping").note) == ("unknown", "HiroLeague's WhatsApp says 'sleeping'")


def test_a_status_that_cant_be_asked_says_why(core, monkeypatch):
    core.connected = False
    s = run(whatsapp.status())
    assert (s.state, s.note) == ("no_core", "TestApp isn't connected to HiroLeague (Settings → HiroLeague)")
    core.connected, core.answer = True, ExtensionRequestError("timeout", "no answer")
    assert run(whatsapp.status()).note == "HiroLeague didn't answer in 10 s"
    testing.outputs(monkeypatch, False)
    assert run(whatsapp.status()).outputs is False


def test_a_status_that_cant_be_read_is_a_whatsapp_error(core):
    core.answer = {"state": "connected"}  # no "running"
    with pytest.raises(whatsapp.WhatsAppError, match="status can't be read"):
        run(whatsapp.status())
