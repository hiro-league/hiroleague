"""Unit tests for the process-wide Kuzu resource registry.

No Kuzu here — the registry is generic (opaque resource + caller-supplied
factory/closer). Covers: one-shared-resource + refcounting, last-release teardown,
factory-failure isolation, write-lock identity, and the FIFO fairness that lets a
waiting writer cut ahead of a busy writer's *next* episode (docs §4.2).
"""

from __future__ import annotations

import asyncio

import pytest

from hirocli.services.knowledge.graph import kuzu_registry


@pytest.fixture(autouse=True)
def _clean_registry():
    """The registry is process-global; clear it around each test so fixed keys
    ("k"/"ws1") don't leak between tests."""
    kuzu_registry._REGISTRY.clear()
    kuzu_registry._LOCKS.clear()
    yield
    kuzu_registry._REGISTRY.clear()
    kuzu_registry._LOCKS.clear()


def test_acquire_shares_one_resource_and_refcounts() -> None:
    calls = {"open": 0, "close": 0}
    resource = object()

    def factory():
        calls["open"] += 1
        return resource

    def closer(r):
        assert r is resource
        calls["close"] += 1

    r1 = kuzu_registry.acquire("k", factory)
    r2 = kuzu_registry.acquire("k", factory)
    assert r1 is resource and r2 is resource
    assert calls["open"] == 1  # opened ONCE, shared by both consumers
    assert kuzu_registry._refcount("k") == 2

    kuzu_registry.release("k", closer)
    assert calls["close"] == 0  # 2nd consumer still holds it → not closed
    assert kuzu_registry._refcount("k") == 1

    kuzu_registry.release("k", closer)
    assert calls["close"] == 1  # last release → closed, file lock freed
    assert kuzu_registry._active_keys() == []


def test_reacquire_after_full_release_reopens() -> None:
    opens = []

    def factory():
        opens.append(1)
        return object()

    kuzu_registry.acquire("k", factory)
    kuzu_registry.release("k", lambda r: None)
    assert kuzu_registry._active_keys() == []
    kuzu_registry.acquire("k", factory)  # reopens
    assert len(opens) == 2


def test_factory_failure_is_not_registered() -> None:
    def boom():
        raise RuntimeError("IO exception: Could not set lock on file …")

    with pytest.raises(RuntimeError):
        kuzu_registry.acquire("k", boom)
    assert kuzu_registry._active_keys() == []  # nothing half-registered


def test_release_unknown_key_is_noop() -> None:
    kuzu_registry.release("never-acquired", lambda r: pytest.fail("closer must not run"))


def test_write_lock_stable_identity() -> None:
    a1 = kuzu_registry.write_lock("k")
    a2 = kuzu_registry.write_lock("k")
    other = kuzu_registry.write_lock("other")
    assert a1 is a2  # same lock for same workspace
    assert a1 is not other  # distinct workspaces → distinct locks


@pytest.mark.asyncio
async def test_write_lock_fifo_fairness_waiter_cuts_ahead() -> None:
    """A busy writer (A) re-requests the lock only AFTER releasing each episode, so a
    waiter (B) that arrived mid-episode runs BEFORE A's next episode. This is the
    property that bounds a chat's wait to ~one episode, not the whole batch (§4.2)."""
    lock = kuzu_registry.write_lock("ws1")
    order: list[str] = []

    async def writer_A() -> None:
        for ep in range(1, 4):
            async with lock:
                order.append(f"A{ep}")
                await asyncio.sleep(0.05)  # holds the pen for "one episode"

    async def writer_B() -> None:
        await asyncio.sleep(0.02)  # start waiting partway through A's episode 1
        async with lock:
            order.append("B")

    await asyncio.gather(writer_A(), writer_B())

    assert order[0] == "A1"
    # B cut in BEFORE A's 2nd episode (FIFO), not after all of A's episodes.
    assert order.index("B") < order.index("A2"), order
