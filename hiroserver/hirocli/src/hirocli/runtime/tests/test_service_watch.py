"""The server stops itself when the WinSW that started it is gone (a real process stands in for WinSW)."""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys

import psutil
import pytest

from hirocli.runtime import service_watch


def test_find_wrapper_finds_the_ancestor_winsw_names() -> None:
    parent = psutil.Process().parent()
    found = service_watch.find_wrapper({service_watch.ENV_WINSW_EXECUTABLE: parent.exe()})
    assert found is not None and found.pid == parent.pid


def test_find_wrapper_without_winsw_finds_nothing() -> None:
    assert service_watch.find_wrapper({}) is None
    assert service_watch.find_wrapper({service_watch.ENV_WINSW_EXECUTABLE: r"C:\nowhere\hiro.exe"}) is None


@pytest.fixture
def stand_in():
    """A process that plays the service's WinSW: alive until the test kills it."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])  # noqa: S603
    yield proc
    proc.kill()
    proc.wait(timeout=10)


def test_the_server_stops_once_its_winsw_is_gone(stand_in, monkeypatch, caplog) -> None:
    monkeypatch.setattr(service_watch, "find_wrapper", lambda: psutil.Process(stand_in.pid))

    async def scenario() -> bool:
        stop = asyncio.Event()
        watcher = asyncio.ensure_future(service_watch.watch_service_wrapper(stop, every_s=0.05))
        await asyncio.sleep(0.3)
        alive_meanwhile = not stop.is_set()
        stand_in.kill()
        stand_in.wait(timeout=10)
        await asyncio.wait_for(watcher, timeout=5)
        return alive_meanwhile and stop.is_set()

    with caplog.at_level(logging.INFO, logger="SERVER"):
        assert asyncio.run(scenario()) is True
    (line,) = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert "WinSW is gone" in line.getMessage()


def test_the_watch_ends_with_the_server(stand_in, monkeypatch) -> None:
    monkeypatch.setattr(service_watch, "find_wrapper", lambda: psutil.Process(stand_in.pid))

    async def scenario() -> None:
        stop = asyncio.Event()
        watcher = asyncio.ensure_future(service_watch.watch_service_wrapper(stop, every_s=5))
        await asyncio.sleep(0.1)
        stop.set()
        await asyncio.wait_for(watcher, timeout=2)  # doesn't wait out its 5 s round

    asyncio.run(scenario())
    assert stand_in.poll() is None  # the stand-in was only watched, never touched


def test_a_wrapper_that_cant_be_found_is_said_once(monkeypatch, caplog) -> None:
    monkeypatch.setattr(service_watch, "find_wrapper", lambda: None)
    with caplog.at_level(logging.WARNING, logger="SERVER"):
        asyncio.run(service_watch.watch_service_wrapper(asyncio.Event()))
    (line,) = caplog.records
    assert "wasn't found" in line.getMessage()
