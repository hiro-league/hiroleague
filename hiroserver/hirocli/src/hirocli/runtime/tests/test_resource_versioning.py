"""Tests for ResourceVersionStore."""

from __future__ import annotations

from hirocli.runtime.resource_versioning import ResourceVersionStore


def test_bump_monotonic_per_resource() -> None:
    store = ResourceVersionStore()
    assert store.get("channels") == 0
    assert store.bump("channels") == 1
    assert store.bump("channels") == 2
    assert store.get("channels") == 2


def test_resources_independent() -> None:
    store = ResourceVersionStore()
    assert store.bump("channels") == 1
    assert store.bump("policy") == 1
    assert store.get("channels") == 1
    assert store.get("policy") == 1
