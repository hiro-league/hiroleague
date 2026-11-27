"""The starter gives a channel plugin's process its start environment: the server's, what the channel's catalog entry
names, and its pairing code. neonize's Go code reads NEONIZE_BOT_TAG from the start environment only, so WhatsApp's
process must start with it off (a reply tagged as a business bot is accepted by WhatsApp and delivered nowhere)."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from hiro_channel_sdk.constants import ENV_PAIRING_CODE
from hirocli.domain.channel_catalog import channel_env
from hirocli.domain.channel_config import ChannelConfig
from hirocli.runtime import extension_starter
from hirocli.runtime.extension_starter import ExtensionStarter, leftovers
from hiro_commons.process_job import ProcessJob


def _started_env(tmp_path: Path, monkeypatch, name: str) -> tuple[list[str], dict[str, str]]:
    seen: dict[str, Any] = {}

    def fake_start(cmd: list[str], env: dict[str, str], out: Any, name: str) -> Any:
        seen.update(cmd=cmd, env=env)
        return SimpleNamespace(pid=4242, poll=lambda: None), ProcessJob(name)

    monkeypatch.setattr(extension_starter, "_start_process", fake_start)
    monkeypatch.setenv("NEONIZE_BOT_TAG", "on")  # the server's own environment never wins over the catalog's
    ctx = SimpleNamespace(workspace_path=tmp_path, log_dir=tmp_path / "logs", config=SimpleNamespace(log_level="INFO"))
    ExtensionStarter(ctx, "ws://127.0.0.1:1").start(ChannelConfig(name=name), "the-code")  # type: ignore[arg-type]
    return seen["cmd"], seen["env"]


def test_whatsapp_starts_with_the_business_bot_tag_off(tmp_path: Path, monkeypatch) -> None:
    cmd, env = _started_env(tmp_path, monkeypatch, "whatsapp")
    assert env["NEONIZE_BOT_TAG"] == "off"
    assert env[ENV_PAIRING_CODE] == "the-code"
    assert "the-code" not in cmd  # the code is never on the command line
    assert cmd[cmd.index("--key-dir") + 1] == str(tmp_path / "channels" / "whatsapp")


def test_a_channel_the_catalog_gives_nothing_keeps_the_servers_environment(tmp_path: Path, monkeypatch) -> None:
    _, env = _started_env(tmp_path, monkeypatch, "devices")
    assert env["NEONIZE_BOT_TAG"] == "on"  # untouched: only WhatsApp's entry names it
    assert env[ENV_PAIRING_CODE] == "the-code"
    assert channel_env("devices") == {} and channel_env("whatsapp") == {"NEONIZE_BOT_TAG": "off"}


def test_a_plugin_of_this_workspace_is_found_by_its_key_dir(tmp_path: Path) -> None:
    channels = tmp_path / "ws" / "channels"
    other = tmp_path / "other" / "channels"
    found = leftovers(channels, [
        (1, ["uv", "run", "python", "-m", "x", "--key-dir", str(channels / "whatsapp")]),  # the launcher
        (2, ["python.exe", "-m", "x", "--key-dir", str(channels / "devices").upper()]),  # Windows: case doesn't matter
        (3, ["python", "-m", "x", "--key-dir", str(other / "whatsapp")]),  # another workspace's
        (4, ["python", "-m", "x", "--key-dir"]),  # no folder after it
        (5, None),  # a process this user can't read
        (6, ["notepad.exe"]),
    ])
    assert found == ([1, 2] if sys.platform == "win32" else [1])
