"""Device chat's access: which devices may connect (paired, pass not expired), the core refusing a frame from any other,
the gateway hearing each change, and the core's own gateway command."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from hiro_commons.keys import generate_private_key, public_key_to_b64

from hirocli.domain import pairing
from hirocli.domain.config import Config
from hirocli.domain.events import DomainEventType
from hirocli.domain.pairing import ApprovedDevice, paired_device_ids, revoke_approved_device, upsert_approved_device
from hirocli.runtime.builtin_gateway import BuiltinGateway, gateway_command
from hirocli.runtime.channel_manager import ChannelManager
from hirocli.runtime.infra_event_handlers import InfraEventHandlers


def _device(device_id: str, *, expires_in_days: int | None = 30) -> ApprovedDevice:
    now = datetime.now(UTC)
    return ApprovedDevice(
        device_id=device_id,
        device_public_key="pk",
        paired_at=now,
        expires_at=None if expires_in_days is None else now + timedelta(days=expires_in_days),
    )


class _Bus:
    def __init__(self) -> None:
        self.events: list[str] = []

    def publish(self, event) -> None:
        self.events.append(event.type)


def test_only_paired_devices_with_a_live_pass_may_connect(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(pairing, "get_domain_event_bus", _Bus)
    upsert_approved_device(tmp_path, _device("mobile-a"))
    upsert_approved_device(tmp_path, _device("mobile-old", expires_in_days=-1))
    upsert_approved_device(tmp_path, _device("mobile-forever", expires_in_days=None))
    assert paired_device_ids(tmp_path) == {"mobile-a", "mobile-forever"}


def test_pairing_and_removing_a_device_say_so(tmp_path: Path, monkeypatch) -> None:
    bus = _Bus()
    monkeypatch.setattr(pairing, "get_domain_event_bus", lambda: bus)
    upsert_approved_device(tmp_path, _device("mobile-a"))
    assert revoke_approved_device(tmp_path, "mobile-a") is True
    assert revoke_approved_device(tmp_path, "mobile-a") is False  # nothing removed: nothing to say
    assert bus.events == [DomainEventType.DEVICES_CHANGED] * 2


def test_the_core_refuses_a_frame_from_a_device_no_longer_paired(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(pairing, "get_domain_event_bus", _Bus)
    upsert_approved_device(tmp_path, _device("mobile-a"))
    cm = ChannelManager.__new__(ChannelManager)
    cm._ctx = SimpleNamespace(workspace_path=tmp_path)

    def frame(sender: str) -> dict:
        return {"routing": {"sender_id": sender}}

    assert cm._from_unpaired_device("devices", frame("mobile-a")) is False
    assert cm._from_unpaired_device("devices", frame("mobile-gone")) is True
    assert cm._from_unpaired_device("whatsapp", frame("someone")) is False  # other channels have their own senders


def test_the_gateway_hears_the_paired_devices(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(pairing, "get_domain_event_bus", _Bus)
    upsert_approved_device(tmp_path, _device("mobile-b"))
    upsert_approved_device(tmp_path, _device("mobile-a"))
    sent: list[tuple] = []

    class _Channels:
        async def send_event_to_channel(self, *args) -> None:
            sent.append(args)

    handlers = InfraEventHandlers(SimpleNamespace(workspace_path=tmp_path))
    handlers._channel_manager = _Channels()
    asyncio.run(handlers.send_allowed_devices())
    assert sent == [("devices", "allowed_devices", {"device_ids": ["mobile-a", "mobile-b"]})]


def test_the_core_runs_its_own_gateway_on_loopback_with_its_own_key(tmp_path: Path) -> None:
    key = generate_private_key()
    ctx = SimpleNamespace(
        workspace_path=tmp_path,
        log_dir=tmp_path / "logs",
        desktop_private_key=key,
        config=Config(gateway_port=7417, gateway_url="ws://127.0.0.1:7417"),
    )
    cmd = gateway_command(ctx)
    assert cmd[1:4] == ["-m", "hirogateway.main", "serve"]
    assert cmd[cmd.index("--desktop-pubkey") + 1] == public_key_to_b64(key.public_key())
    assert (cmd[cmd.index("--host") + 1], cmd[cmd.index("--port") + 1]) == ("127.0.0.1", "7417")
    assert ctx.config.gateway_connect_url() == "ws://127.0.0.1:7417"


def test_a_gateway_run_elsewhere_is_used_as_named(tmp_path: Path) -> None:
    config = Config(gateway_builtin=False, gateway_url="ws://relay.example:8765")
    assert config.gateway_connect_url() == "ws://relay.example:8765"
    assert BuiltinGateway(SimpleNamespace(config=config)).wanted() is False
