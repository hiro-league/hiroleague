"""neonize faked for the channel's tests: the shared dev venv can't import neonize 0.5.x (it needs protobuf 7)."""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

_NEONIZE_MODULES = (
    "neonize",
    "neonize.aioze",
    "neonize.aioze.client",
    "neonize.aioze.events",
    "neonize.exc",
    "neonize.proto",
    "neonize.proto.waCompanionReg",
    "neonize.proto.waCompanionReg.WAWebProtobufsCompanionReg_pb2",
    "neonize.proto.waE2E",
    "neonize.proto.waE2E.WAWebProtobufsE2E_pb2",
    "neonize.utils",
    "neonize.utils.enum",
)


class _Anything:
    """Stands in for any neonize class/enum/function the module imports."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __getattr__(self, name: str) -> Any:
        return _Anything()

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return _Anything()


def _stub_module(name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__getattr__ = lambda attr: _Anything()  # type: ignore[attr-defined]
    module.__path__ = []  # type: ignore[attr-defined]  # importable as a package
    return module


@pytest.fixture
def stub_neonize(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every neonize module the channel imports, as stand-ins."""
    for name in _NEONIZE_MODULES:
        monkeypatch.setitem(sys.modules, name, _stub_module(name))
