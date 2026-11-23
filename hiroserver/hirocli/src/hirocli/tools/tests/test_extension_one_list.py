"""The one list of every extension (Unified communication, phase 2): the list tool gives a channel and an app one row
shape, and the remove tool takes the path of the row's kind: an app is forgotten, a channel is removed and its program
uninstalled, the mandatory channel is refused."""

from __future__ import annotations

import logging

import pytest

from hiro_commons.constants.domain import MANDATORY_CHANNEL_NAME
from hirocli.domain.channel_config import ChannelConfig, load_channel_config, save_channel_config
from hirocli.domain.channel_descriptor import ChannelDescriptor, save_channel_descriptor
from hirocli.domain.extensions import add_paired_extension, list_paired_extensions
from hirocli.tools import channel as channel_tools
from hirocli.tools import extension as extension_tools
from hirocli.tools.extension import ExtensionListTool, ExtensionRemoveTool

_HOME_INFO = {
    "name": "home",
    "version": "0.1.0",
    "description": "HomeHiro: the home's cameras, people and devices",
    "offers": {
        "knows": [{"method": "home.checks", "name": "Home's checks", "says": "Whether the MQTT link works"}],
        "can_do": [],
        "tells": [],
        "shows": [{"kind": "site", "title": "Home", "icon": "house", "url": "http://home.hiro.local", "roles": []}],
    },
    "uses": [{"id": "ask", "name": "Ask a camera"}],
    "voice_uses": [{"id": "say", "name": "Say a notice"}],
}


class _Uninstalls:
    """Stands in for `uv tool uninstall`, which is the whole PC's: a test never runs it."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.names: list[str] = []

    def execute(self, channel_name: str, package: str | None = None) -> object:
        self.names.append(channel_name)
        if self.fail:
            raise RuntimeError("Uninstall failed (exit 2): no such tool")
        return object()


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(channel_tools, "_resolve_path", lambda _ws: tmp_path)
    monkeypatch.setattr(extension_tools, "_resolve_path", lambda _ws: tmp_path)
    save_channel_config(tmp_path, ChannelConfig(name="whatsapp", enabled=True))
    save_channel_descriptor(
        tmp_path,
        ChannelDescriptor(
            channel="whatsapp",
            version="0.1.0",
            config_schema={"type": "object", "properties": {"send_read_receipts": {"type": "boolean"}}},
            capabilities={"pairing": "qr", "actions": ["logout"]},
        ),
    )
    save_channel_config(tmp_path, ChannelConfig(name=MANDATORY_CHANNEL_NAME, enabled=True))
    add_paired_extension(tmp_path, name="home", public_key="pk", info=_HOME_INFO)
    return tmp_path


def _rows() -> dict[str, dict]:
    return {row["name"]: row for row in ExtensionListTool().execute().extensions}


def _id_of(workspace, name: str) -> str:
    return next(e.extension_id for e in list_paired_extensions(workspace, kind=None) if e.name == name)


def test_the_list_holds_both_kinds_in_one_row_shape(workspace) -> None:
    rows = _rows()

    assert set(rows) == {"whatsapp", MANDATORY_CHANNEL_NAME, "home"}
    assert rows["whatsapp"].keys() == rows["home"].keys()


def test_a_channel_row_says_what_the_core_keeps_for_it(workspace) -> None:
    whatsapp = _rows()["whatsapp"]

    assert whatsapp["kind"] == "channel"
    assert whatsapp["label"] == "WhatsApp"  # the channel catalog's label
    assert whatsapp["description"]  # the catalog's, until the plugin describes itself
    assert whatsapp["enabled"] is True
    assert whatsapp["started_by_core"] and whatsapp["relays_chat"]
    assert whatsapp["has_settings"] is True
    assert whatsapp["pairing"] == "qr"
    assert whatsapp["mandatory"] is False
    assert whatsapp["site"] == ""


def test_an_app_row_says_what_its_description_holds(workspace) -> None:
    home = _rows()["home"]

    assert home["kind"] == "app"
    assert home["label"] == "Home"  # its site's title
    assert home["enabled"] is None  # an app has no switch
    assert home["has_settings"] is False and home["pairing"] == ""
    assert home["site"] == "http://home.hiro.local"
    assert home["offers"] == [{"name": "Home's checks", "says": "Whether the MQTT link works"}]
    assert home["uses"] == ["Ask a camera", "Say a notice"]


def test_the_mandatory_channel_is_marked(workspace) -> None:
    assert _rows()[MANDATORY_CHANNEL_NAME]["mandatory"] is True


def test_removing_an_app_forgets_it_and_uninstalls_nothing(workspace, monkeypatch) -> None:
    uninstalls = _Uninstalls()
    monkeypatch.setattr(extension_tools, "ChannelUninstallTool", lambda: uninstalls)

    result = ExtensionRemoveTool().execute(_id_of(workspace, "home"))

    assert result.removed and result.kind == "app"
    assert "home" not in _rows()
    assert uninstalls.names == []


def test_removing_a_channel_deletes_its_settings_and_uninstalls_its_program(workspace, monkeypatch) -> None:
    uninstalls = _Uninstalls()
    monkeypatch.setattr(extension_tools, "ChannelUninstallTool", lambda: uninstalls)

    result = ExtensionRemoveTool().execute(_id_of(workspace, "whatsapp"))

    assert result.removed and result.kind == "channel" and result.uninstalled
    assert uninstalls.names == ["whatsapp"]
    assert load_channel_config(workspace, "whatsapp") is None
    assert "whatsapp" not in _rows()


def test_a_channel_whose_uninstall_fails_is_still_removed_and_says_so(workspace, monkeypatch, caplog) -> None:
    monkeypatch.setattr(extension_tools, "ChannelUninstallTool", lambda: _Uninstalls(fail=True))
    caplog.set_level(logging.WARNING)

    result = ExtensionRemoveTool().execute(_id_of(workspace, "whatsapp"))

    assert result.removed and not result.uninstalled
    assert "whatsapp" not in _rows()
    assert any("stayed installed" in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)


def test_the_mandatory_channel_is_refused(workspace, monkeypatch) -> None:
    uninstalls = _Uninstalls()
    monkeypatch.setattr(extension_tools, "ChannelUninstallTool", lambda: uninstalls)

    with pytest.raises(ValueError, match="mandatory"):
        ExtensionRemoveTool().execute(_id_of(workspace, MANDATORY_CHANNEL_NAME))

    assert MANDATORY_CHANNEL_NAME in _rows()
    assert uninstalls.names == []


def test_an_unknown_id_removes_nothing(workspace) -> None:
    assert ExtensionRemoveTool().execute("no-such-id").removed is False
    assert len(_rows()) == 3
