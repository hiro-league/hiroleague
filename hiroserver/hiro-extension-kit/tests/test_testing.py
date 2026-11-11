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
    core = FakeCore()
    only = core.person("Mona", "owner")
    with pytest.raises(ExtensionRequestError, match="only Owner") as info:
        asyncio.run(core.request("people.update", {"person_id": only["person_id"], "role_id": "adult"}))
    assert info.value.code == "invalid_params"
