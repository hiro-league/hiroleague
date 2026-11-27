"""mac_libmagic: on a Mac it loads pylibmagic (libmagic for neonize's python-magic); elsewhere it loads nothing."""

from __future__ import annotations

import sys
import types

from hiro_channel_whatsapp import mac_libmagic


def test_a_mac_loads_pylibmagic(monkeypatch):
    # A stand-in pylibmagic: the real one is installed on Macs only.
    fake = types.ModuleType("pylibmagic")
    monkeypatch.setitem(sys.modules, "pylibmagic", fake)
    monkeypatch.setattr(sys, "platform", "darwin")
    assert mac_libmagic.load() is True


def test_elsewhere_nothing_is_loaded(monkeypatch):
    monkeypatch.delitem(sys.modules, "pylibmagic", raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    assert mac_libmagic.load() is False
    assert "pylibmagic" not in sys.modules
