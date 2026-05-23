"""Tests for KnowledgeManager lifecycle and preference reactors."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from hirocli.runtime.knowledge_manager import KnowledgeManager
from hirocli.runtime.server_context import ServerContext
from hirocli.services.knowledge.test_service import FakeEmbedder


def _build_ctx(tmp_path: Path) -> ServerContext:
    from hirocli.domain.config import load_config
    from hirocli.domain.crypto import load_or_create_master_key

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    config = load_config(workspace)
    stop_event = asyncio.Event()
    return ServerContext(
        workspace_path=workspace,
        workspace_name="test",
        config=config,
        stop_event=stop_event,
        desktop_private_key=load_or_create_master_key(workspace, filename=config.master_key_file),
    )


@pytest.mark.asyncio
async def test_knowledge_manager_exposes_service_on_ctx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "hirocli.services.knowledge.create_knowledge_service",
        lambda workspace_path, **kwargs: __import__(
            "hirocli.services.knowledge.service", fromlist=["KnowledgeService"]
        ).KnowledgeService(workspace_path, embedder=FakeEmbedder()),
    )
    ctx = _build_ctx(tmp_path)
    manager = KnowledgeManager(ctx)
    assert ctx.knowledge_manager is manager
    assert manager.service is ctx.knowledge_manager.service
    await manager.close()
    assert ctx.knowledge_manager is None


@pytest.mark.asyncio
async def test_knowledge_manager_close_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "hirocli.services.knowledge.create_knowledge_service",
        lambda workspace_path, **kwargs: __import__(
            "hirocli.services.knowledge.service", fromlist=["KnowledgeService"]
        ).KnowledgeService(workspace_path, embedder=FakeEmbedder()),
    )
    ctx = _build_ctx(tmp_path)
    manager = KnowledgeManager(ctx)
    await manager.close()
    await manager.close()
    assert ctx.knowledge_manager is None
