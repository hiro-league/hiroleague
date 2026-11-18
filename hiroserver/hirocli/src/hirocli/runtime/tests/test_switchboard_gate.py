"""The core's gate for apps' requests: a test environment's switchboard refuses AI, voices and WhatsApp it may not
reach, with the method's own error code; live (no switchboard named) refuses nothing."""

import json

import pytest
from hiro_commons import switchboard

from hirocli.runtime.request_handler import RequestRefused, gate


@pytest.fixture
def board(tmp_path, monkeypatch):
    def use(modes):
        path = tmp_path / "switchboard.json"
        path.write_text(json.dumps({"place": "env2", "preset": "Safe", "modes": modes}), encoding="utf-8")
        monkeypatch.setattr(switchboard, "_board", switchboard.read({switchboard.ENV: str(path)}))

    yield use
    monkeypatch.setattr(switchboard, "_board", None)


def test_live_refuses_nothing(monkeypatch):
    monkeypatch.setattr(switchboard, "_board", switchboard.read({}))
    gate("ai", "failed")
    gate("whatsapp", "whatsapp_failed")


def test_a_system_off_or_fake_is_refused_with_the_methods_code_and_the_place(board):
    board({"ai": "off", "voices": "fake", "whatsapp": "real"})
    with pytest.raises(RequestRefused) as off:
        gate("ai", "failed")
    assert off.value.code == "failed" and "AI is off in env2" in off.value.message
    with pytest.raises(RequestRefused, match="Voices is fake in env2"):
        gate("voices", "failed")
    gate("whatsapp", "whatsapp_failed")  # real: goes on
