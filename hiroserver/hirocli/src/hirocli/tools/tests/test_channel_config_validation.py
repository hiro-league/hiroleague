"""ChannelConfigSetTool validates writes against the plugin's declared schema (§5.1)."""

from __future__ import annotations

import pytest

from hirocli.domain.channel_config import ChannelConfig, save_channel_config
from hirocli.domain.channel_descriptor import ChannelDescriptor, save_channel_descriptor
from hirocli.tools import channel as channel_tools
from hirocli.tools.channel import ChannelConfigSetTool

_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "owner_number": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "send_read_receipts": {"type": "boolean"},
    },
}


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    # Point the Tool's workspace resolver at a throwaway dir, then seed a configured
    # channel plus its registration descriptor.
    monkeypatch.setattr(channel_tools, "_resolve_path", lambda _ws: tmp_path)
    save_channel_config(tmp_path, ChannelConfig(name="whatsapp", enabled=True))
    save_channel_descriptor(
        tmp_path,
        ChannelDescriptor(channel="whatsapp", version="0.1.0", config_schema=_SCHEMA),
    )
    return tmp_path


def test_set_coerces_int_phone_to_string(workspace) -> None:
    # CLI passes the number as a JSON int; it must be stored as a string per schema.
    result = ChannelConfigSetTool().execute("whatsapp", "owner_number", "201223504849")
    assert result.config["owner_number"] == "201223504849"


def test_set_rejects_unknown_key(workspace) -> None:
    with pytest.raises(ValueError, match="Invalid channel config"):
        ChannelConfigSetTool().execute("whatsapp", "ownr_number", "123")


def test_set_rejects_bad_type(workspace) -> None:
    with pytest.raises(ValueError, match="Invalid channel config"):
        ChannelConfigSetTool().execute("whatsapp", "send_read_receipts", "maybe")


def test_set_without_descriptor_passes_through(tmp_path, monkeypatch) -> None:
    # A channel that never registered has no descriptor → no validation.
    monkeypatch.setattr(channel_tools, "_resolve_path", lambda _ws: tmp_path)
    save_channel_config(tmp_path, ChannelConfig(name="echo", enabled=True))
    result = ChannelConfigSetTool().execute("echo", "anything", "goes")
    assert result.config["anything"] == "goes"


# --- secret fields (§5.6) ---------------------------------------------------

_SECRET_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"bot_token": {"type": "string", "secret": True}},
}


@pytest.fixture
def secret_workspace(tmp_path, monkeypatch):
    from hirocli.domain import channel_secret_store as css

    monkeypatch.setattr(channel_tools, "_resolve_path", lambda _ws: tmp_path)
    # Secret writes need a registry-backed workspace id + a working keyring.
    monkeypatch.setattr(channel_tools, "workspace_id_for_path", lambda _p: "ws1")
    kr: dict[tuple[str, str], str] = {}
    monkeypatch.setattr(css.keyring_secrets, "set_secret", lambda s, u, v: kr.__setitem__((s, u), v))
    monkeypatch.setattr(css.keyring_secrets, "get_secret", lambda s, u: kr.get((s, u)))
    monkeypatch.setattr(css.keyring_secrets, "delete_secret", lambda s, u: kr.pop((s, u), None))
    save_channel_config(tmp_path, ChannelConfig(name="telegram", enabled=True))
    save_channel_descriptor(
        tmp_path,
        ChannelDescriptor(channel="telegram", version="0.1.0", config_schema=_SECRET_SCHEMA),
    )
    return tmp_path, kr


def test_secret_value_goes_to_keyring_not_config(secret_workspace) -> None:
    _tmp, kr = secret_workspace
    result = ChannelConfigSetTool().execute("telegram", "bot_token", "SECRET-XYZ")
    # Config holds only the marker; the value lives in the keyring.
    assert result.config["bot_token"] == {"__secret__": True}
    assert "SECRET-XYZ" not in str(result.config)
    assert ("hiroleague:ws1:channel:telegram", "bot_token") in kr
    assert kr[("hiroleague:ws1:channel:telegram", "bot_token")] == "SECRET-XYZ"


def test_unset_secret_deletes_from_keyring(secret_workspace) -> None:
    _tmp, kr = secret_workspace
    ChannelSetTool = ChannelConfigSetTool()
    ChannelSetTool.execute("telegram", "bot_token", "SECRET-XYZ")
    result = ChannelSetTool.execute("telegram", "bot_token", None)
    assert "bot_token" not in result.config
    assert ("hiroleague:ws1:channel:telegram", "bot_token") not in kr
