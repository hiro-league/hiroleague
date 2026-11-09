"""Phase 7b end to end: an extension's voice uses, voice.speak and voice.profiles over the real extension socket.

The SDK's client pairs with a temporary core; it declares a voice use, the core speaks with the profile picked
for "home:speak" (the provider is faked: nothing is paid for), a second time from the clip cache, and counts
the paid clip in AI usage. A use with no profile is no_profile; the app can't call the voice methods.
"""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from hiro_channel_sdk.constants import METHOD_VOICE_PROFILES, METHOD_VOICE_SPEAK
from hiro_channel_sdk.extension import (
    STATUS_CONNECTED,
    STATUS_NOT_PAIRED,
    ExtensionClient,
    ExtensionCredentials,
    ExtensionInfo,
    ExtensionRequestError,
    ExtensionVoiceUse,
    build_request,
)
from hirocli.domain.config import Config
from hirocli.domain.extensions import list_paired_extensions, start_extension_pairing
from hirocli.domain.preferences import VoiceProfile, WorkspacePreferences
from hirocli.runtime.extension_manager import ExtensionManager
from hirocli.runtime.preferences_runtime import WorkspacePreferencesRuntime
from hirocli.runtime.request_handler import CALLER_DEVICE, CALLER_EXTENSION, RequestHandler
from hirocli.runtime.tests.test_ai_for_extensions import _free_port, _Sink, _wait_for
from hirocli.runtime.uses_for_extensions import USES_REQUEST_HANDLERS
from hirocli.runtime.voice_for_extensions import VOICE_REQUEST_HANDLERS
from hirocli.services.ai_usage.store import read_rows
from hirocli.services.voice import engine
from hirocli.services.voice.kit import Speech
from hirocli.services.voice.tests.test_voice import _tone

DOOR = {"label": "Door alert", "model": "openai:gpt-4o-mini-tts", "voice": "sage", "speed": 1.1}


def _core(workspace: Path, port: int) -> tuple[ExtensionManager, RequestHandler, SimpleNamespace]:
    prefs = WorkspacePreferences.model_validate(
        {"voice": {"profiles": {"door": DOOR}, "uses": {"home:speak": "door", "home:story": None}}}
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
    for name, fn, callers in (*VOICE_REQUEST_HANDLERS, *USES_REQUEST_HANDLERS):
        handler.register(name, fn, callers=callers)
    manager = ExtensionManager(ctx, handler)  # type: ignore[arg-type]
    ctx.extension_manager = manager
    return manager, handler, ctx


def test_an_extension_speaks_with_its_uses_profile_from_the_cache_the_second_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    said: list[tuple[str, str]] = []

    async def fake_synthesize(path: Path, profile: VoiceProfile, text: str) -> Speech:
        said.append((profile.voice, text))
        return Speech(_tone(0.4), 24000, 0.4, 0.0015, False, tokens_in=6)

    monkeypatch.setattr(engine, "synthesize", fake_synthesize)

    async def scenario() -> None:
        workspace = tmp_path / "ws"
        port = _free_port()
        manager, handler, ctx = _core(workspace, port)
        server = asyncio.create_task(manager.run())
        await _wait_for(lambda: manager.listen_state()["listening"])
        info = ExtensionInfo(name="home", voice_uses=[ExtensionVoiceUse(id="speak", name="Speak")])
        client = ExtensionClient(f"ws://127.0.0.1:{port}", info, ExtensionCredentials(tmp_path / "home"))
        running = asyncio.create_task(client.run())
        await _wait_for(lambda: client.status == STATUS_NOT_PAIRED)
        client.pair(start_extension_pairing(workspace, code_length=6, ttl_seconds=60).code)
        await _wait_for(lambda: client.status == STATUS_CONNECTED)

        [paired] = list_paired_extensions(workspace)
        assert paired.declared_voice_uses() == [{"id": "speak", "name": "Speak"}]

        listed = await client.request(METHOD_VOICE_PROFILES)
        assert listed["uses"] == {"speak": "door", "story": None}
        assert listed["profiles"] == [{"id": "door", "name": "Door alert", "line": "OpenAI · gpt-4o-mini-tts · sage · 1.1×"}]

        first = await client.request(METHOD_VOICE_SPEAK, {"use": "speak", "text": "Someone is at the door", "label": "Front door"}, timeout=10)
        assert base64.b64decode(first["ogg_b64"])[:4] == b"OggS"
        assert (first["cached"], first["profile_id"], first["voice"], first["seconds"]) == (False, "door", "sage", pytest.approx(0.4))
        assert len(base64.b64decode(first["waveform_b64"])) == 64
        again = await client.request(METHOD_VOICE_SPEAK, {"use": "speak", "text": "Someone is at the door"}, timeout=10)
        assert again["cached"] is True and again["ogg_b64"] == first["ogg_b64"]
        assert said == [("sage", "Someone is at the door")]

        # Only the paid clip is counted: speech, from home, its use and label.
        rows = read_rows(workspace, datetime.now(UTC) - timedelta(hours=2), datetime.now(UTC) + timedelta(hours=1))
        assert [(r["kind"], r["source"], r["use_id"], r["label"], r["requests"]) for r in rows] == [
            ("speech", "home", "speak", "Front door", 1)
        ]

        # A use with no profile picked: no_profile. An unknown person: invalid.
        with pytest.raises(ExtensionRequestError) as err:
            await client.request(METHOD_VOICE_SPEAK, {"use": "story", "text": "Once upon a time"})
        assert err.value.code == "no_profile"
        with pytest.raises(ExtensionRequestError) as err:
            await client.request(METHOD_VOICE_SPEAK, {"use": "speak", "text": "Hi", "person": "nobody"})
        assert err.value.code == "invalid"

        # HomeHiro picks its own use's profile (saved in voice.uses); an undeclared use or an unknown profile is invalid.
        assert await client.request("voice.uses.set", {"use": "speak", "profile": None}) == {"use": "speak", "profile": None}
        assert ctx.preferences.current.voice.uses["home:speak"] is None
        await client.request("voice.uses.set", {"use": "speak", "profile": "door"})
        assert ctx.preferences.current.voice.uses["home:speak"] == "door"
        for bad in ({"use": "story", "profile": "door"}, {"use": "speak", "profile": "gone"}):
            with pytest.raises(ExtensionRequestError) as err:
                await client.request("voice.uses.set", bad)
            assert err.value.code == "invalid"

        # The app (a device) can't call the voice methods.
        device_msg = build_request(METHOD_VOICE_SPEAK, {"use": "speak", "text": "x"}, sender_id="phone", direction="inbound")
        refused = await handler.handle(device_msg, emit_outbound=_Sink(), caller=CALLER_DEVICE)
        assert refused is not None and json.loads(refused.content[0].body)["error"]["code"] == "method_not_found"

        await client.stop()
        ctx.stop_event.set()
        await asyncio.wait_for(asyncio.gather(server, running, return_exceptions=True), timeout=5)

    asyncio.run(scenario())


def test_voice_methods_are_extensions_only() -> None:
    from hirocli.runtime.request_methods import _REGISTERED_HANDLERS

    callers = {name: who for name, _, who in _REGISTERED_HANDLERS}
    assert callers[METHOD_VOICE_SPEAK] == frozenset({CALLER_EXTENSION})
    assert callers[METHOD_VOICE_PROFILES] == frozenset({CALLER_EXTENSION})
