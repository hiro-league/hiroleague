"""The kit's test helpers (testing.py): the fake core answers like the core, and nothing reaches the network."""

import asyncio
import subprocess
import sys
import textwrap

import pytest
from hiro_channel_sdk import ExtensionRequestError

from hiro_extension_kit.testing import FakeCore

GUARDED = textwrap.dedent("""
    import socket, tempfile
    from pathlib import Path
    from hiro_extension_kit import identity
    d = Path(tempfile.mkdtemp())
    identity.setup(name="testapp", title="TestApp", package=d, data_dir=d, static_dir=d)
    from hiro_extension_kit import testing
    testing.guard_network()
    testing.guard_network()  # a second call changes nothing
    try:
        socket.create_connection(("192.0.2.1", 80), timeout=1)
    except RuntimeError as e:
        print("refused:", e)
    server = socket.create_server(("127.0.0.1", 0))
    socket.create_connection(server.getsockname(), timeout=1).close()
    print("local ok")
""")


def test_the_network_beyond_this_computer_is_refused():
    """In a process of its own: the guard stays on for the rest of a process, and this one runs the workspace's tests."""
    done = subprocess.run([sys.executable, "-c", GUARDED], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert "refused: Tests may not use the network (tried 192.0.2.1" in done.stdout  # at its lookup or its connect
    assert "local ok" in done.stdout


def test_another_extension_answers_while_connected_and_offering():
    core = FakeCore()
    core.extensions["home"] = {"home.speak": {"said": True}, "home.devices": lambda p: {"asked": p}}

    def ask(to, method, params=None):
        return asyncio.run(core.ask(to, method, params))

    assert ask("home", "home.speak") == {"said": True}
    assert ask("home", "home.devices", {"x": 1}) == {"asked": {"x": 1}}
    with pytest.raises(ExtensionRequestError) as info:
        ask("home", "home.checks")
    assert info.value.code == "not_offered"
    core.away.add("home")
    with pytest.raises(ExtensionRequestError) as info:
        ask("home", "home.speak")
    assert info.value.code == "not_connected"
    with pytest.raises(ExtensionRequestError) as info:
        ask("net", "net.usage")
    assert info.value.code == "not_connected"
    assert core.asked[0] == ("ask:home.speak", {})


def test_the_family_list_refuses_like_the_core():
    """Permissions phase 8: no app gives or takes the Owner role, nor adds, renames or removes a role."""
    core = FakeCore()
    only = core.person("Mona", "owner")
    mark = core.person("Mark", "adult")
    for method, params in [("people.update", {"person_id": only["person_id"], "role_id": "adult"}),
                           ("people.update", {"person_id": mark["person_id"], "role_ids": ["owner", "adult"]}),
                           ("people.add", {"name": "Lea", "role_ids": ["owner"]}),
                           ("roles.add", {"name": "Guests"}), ("roles.remove", {"role_id": "kid"})]:
        with pytest.raises(ExtensionRequestError) as info:
            asyncio.run(core.request(method, params))
        assert info.value.code == "not_allowed", (method, params)
    with pytest.raises(ExtensionRequestError, match="no role 'guest'") as info:
        asyncio.run(core.request("people.update", {"person_id": mark["person_id"], "role_ids": ["guest"]}))
    assert info.value.code == "invalid_params"


def test_the_core_holds_an_app_to_what_it_is_approved_for():
    """By default an app is approved for everything (as one paired before approvals); a test sets what the owner
    approved, and a method needing more answers not_approved, as the SDK's table says."""
    core = FakeCore()
    core.answers.update({"ai.ask": {"text": "yes"}, "notify": {"results": []}})
    assert asyncio.run(core.request("ai.ask", {"use": "x"})) == {"text": "yes"}
    core.approved = ["people.notify", ("apps.ask", "home")]
    with pytest.raises(ExtensionRequestError, match="isn't approved to ask AI") as info:
        asyncio.run(core.request("ai.ask", {"use": "x"}))
    assert info.value.code == "not_approved"
    assert asyncio.run(core.request("notify", {})) == {"results": []}
    core.extensions = {"home": {"home.speak": {"ok": True}}, "net": {"net.usage": {}}}
    assert asyncio.run(core.ask("home", "home.speak")) == {"ok": True}
    with pytest.raises(ExtensionRequestError) as info:
        asyncio.run(core.ask("net", "net.usage"))
    assert info.value.code == "not_approved"
    with pytest.raises(ExtensionRequestError) as info:
        asyncio.run(core.request("whatsapp.send", {"to": "20100"}))  # never on its own once it declares what it asks
    assert info.value.code == "not_allowed"


def test_the_persons_proof_comes_from_signing_in_and_is_taken_out_of_the_params():
    core = FakeCore()
    owner, adult = core.person("Mona", "owner"), core.person("Mark", "adult")
    who = asyncio.run(core.request("auth.code", {"code": core.sign_in_code(owner)}))
    assert who["person_id"] == owner["person_id"] and who["token"]
    asyncio.run(core.request("people.update", {"person_id": adult["person_id"], "name": "Marc",
                                               "_signed_in": who["token"]}))
    assert core.asked[-1] == ("people.update", {"person_id": adult["person_id"], "name": "Marc"})
    assert core.signed_in == [("people.update", who["token"])]
    theirs = asyncio.run(core.request("auth.code", {"code": core.sign_in_code(adult)}))["token"]
    with pytest.raises(ExtensionRequestError, match="only the owner") as info:
        asyncio.run(core.request("whatsapp.check", {"numbers": [], "_signed_in": theirs}))
    assert info.value.code == "not_allowed"
    core.approved = []  # approved for nothing: not even to act for the people signed in to it
    with pytest.raises(ExtensionRequestError) as info:
        asyncio.run(core.request("people.update", {"person_id": adult["person_id"], "_signed_in": who["token"]}))
    assert info.value.code == "not_approved"
    with pytest.raises(ExtensionRequestError) as info:
        asyncio.run(core.request("people.update", {"person_id": adult["person_id"]}))  # no proof
    assert info.value.code == "sign_in_again"
