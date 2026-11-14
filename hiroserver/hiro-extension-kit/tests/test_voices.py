"""Voices from HiroLeague (voices.py, Phase 7b): an app speaks through the core (`voice.speak`), lists the core's voice
profiles for its pickers (`voice.profiles`), saves its Speak default there (`voice.uses.set`), and finds the core's admin
for its Edit links. Against a fake core: nothing is spoken.

Shared-code plan, step 1: HomeHiro's and NetHiro's tests each had this file; it is tested once, here. Which voice use an
app declares (HomeHiro: Speak; NetHiro: none) stays in the app's tests. The test app declares Speak (conftest.py)."""

import asyncio
import base64

import pytest
from hiro_channel_sdk import ExtensionRequestError
from sqlmodel import Session

from hiro_extension_kit import voices
from hiro_extension_kit.db import engine
from hiro_extension_kit.errors import Invalid, Unavailable
from hiro_extension_kit.hiroleague import check_admin_url, derived_admin_url
from hiro_extension_kit.testing import FakeCore, FakeLink

PROFILES = {
    "profiles": [{"id": "door", "name": "Door alert", "line": "OpenAI · gpt-4o-mini-tts · sage"},
                 {"id": "hh-abc123", "name": "Hiro", "line": "Google · gemini-3.8-flash-tts · Hiro"}, {"name": "no id"}],
    "uses": {"speak": "door"},
}
CLIP = {"ogg_b64": base64.b64encode(b"OggS-clip").decode(), "seconds": 2.5, "waveform_b64": base64.b64encode(bytes(64)).decode(),
        "cached": False, "cost": 0.0012, "profile_id": "door", "profile_name": "Door alert", "provider": "openai",
        "model": "gpt-4o-mini-tts", "voice": "sage"}


@pytest.fixture
def core(monkeypatch):
    fake = FakeCore()
    fake.answers["voice.profiles"] = PROFILES
    fake.answers["voice.speak"] = CLIP
    fake.answers["voice.uses.set"] = lambda params: {"use": params["use"], "profile": params["profile"]}
    monkeypatch.setattr(voices, "link", FakeLink(fake))
    return fake


def test_the_cores_profiles_and_the_speak_default_are_read_and_listed_for_the_pickers(core):
    read = asyncio.run(voices.read())
    assert read.reachable and read.default_id == "door"
    assert [(p.id, p.name) for p in read.profiles] == [("door", "Door alert"), ("hh-abc123", "Hiro")]  # no id: left out
    with Session(engine) as s:
        assert voices.choices(s) == [{"id": "door", "name": "Door alert"}, {"id": "hh-abc123", "name": "Hiro"}]


def test_the_list_is_kept_for_after_a_restart(core):
    asyncio.run(voices.refresh())
    voices._known = voices.Known()  # as after a restart: read back from the database
    with Session(engine) as s:
        assert [c["id"] for c in voices.choices(s)] == ["door", "hh-abc123"]


def test_speaking_asks_the_core_and_an_old_pick_asks_by_its_imported_id(core):
    asyncio.run(voices.read())
    clip = asyncio.run(voices.speak("abc123", "Someone is at the door", label="cam1"))
    method, params = core.asked[-1]
    assert method == "voice.speak"
    assert params == {"use": "speak", "text": "Someone is at the door", "profile": "hh-abc123", "label": "cam1"}
    assert (clip.ogg, clip.seconds, clip.cost, clip.cached, clip.profile_name) == (b"OggS-clip", 2.5, 0.0012, False, "Door alert")
    asyncio.run(voices.speak(None, "Hi"))
    assert "profile" not in core.asked[-1][1]  # no pick: the core speaks with the Speak default


@pytest.mark.parametrize(("code", "error"), [("no_profile", Invalid), ("invalid", Invalid), ("failed", voices.VoiceError),
                                            ("timeout", voices.VoiceError), ("not_connected", Unavailable)])
def test_the_cores_refusals_are_the_errors_callers_handle(core, code, error):
    core.answers["voice.speak"] = ExtensionRequestError(code, "nope")
    with pytest.raises(error):
        asyncio.run(voices.speak("door", "Hi"))


def test_without_the_core_nothing_is_said_and_the_last_list_stays(core):
    asyncio.run(voices.read())
    core.answers["voice.profiles"] = ExtensionRequestError("internal_error", "boom")
    asyncio.run(voices.refresh())
    core.connected = False
    with pytest.raises(Unavailable):
        asyncio.run(voices.speak("door", "Hi"))
    read = asyncio.run(voices.read())
    assert not read.reachable and read.error == voices._no_core() and len(read.profiles) == 2
    with Session(engine) as s:
        assert len(voices.choices(s)) == 2


def test_the_speak_default_is_saved_in_the_core(core):
    asyncio.run(voices.set_default("hh-abc123"))
    assert ("voice.uses.set", {"use": "speak", "profile": "hh-abc123"}) in core.asked


def test_the_admin_address_is_set_or_derived_from_the_cores_host_and_port():
    # a core on this machine (127.0.0.1, localhost) is no address a browser can use, so its LAN name (NetHiro's Phase 9b
    # fix, the kit's since backend kit step 5)
    assert derived_admin_url("ws://127.0.0.1:18082", 18083) == "http://hiro.local"
    assert derived_admin_url("ws://localhost:18082", 18083) == "http://hiro.local"
    assert derived_admin_url("ws://simone.local:18082/x", 18083) == "http://simone.local:18083"
    assert derived_admin_url("", 18083) == "" and derived_admin_url("ws://h:1", None) == ""
    assert check_admin_url(" http://hiro.local/ ") == "http://hiro.local"
    with pytest.raises(Invalid):
        check_admin_url("hiro.local")
