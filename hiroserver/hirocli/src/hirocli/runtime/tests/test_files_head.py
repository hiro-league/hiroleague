"""``files.head`` resolves a ``character_photo:`` ref to blob metadata."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hirocli.domain.blob_store import (
    DEFAULT_CHUNK_SIZE,
    blob_id_for_file,
    chunk_count_for_size,
)
from hirocli.domain.character import (
    resolve_character_photo_file_for_http,
    seed_default_characters,
)
from hirocli.runtime.request_handler import RequestContext
from hirocli.runtime.request_methods import handle_files_head


@pytest.mark.asyncio
async def test_files_head_character_photo(
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tmp_path = tmp_path_factory.mktemp("ws")
    seed_default_characters(tmp_path)
    path, media_type = resolve_character_photo_file_for_http(tmp_path, "hiro")
    expected_blob = blob_id_for_file(path)
    expected_size = path.stat().st_size
    expected_chunks = chunk_count_for_size(expected_size, DEFAULT_CHUNK_SIZE)

    # FilesHeadTool resolves workspace via the registry; route the test workspace through it.
    from hirocli.tools import files as files_tools

    monkeypatch.setattr(files_tools, "_workspace_path", lambda _name: tmp_path)

    srv = SimpleNamespace(workspace_path=tmp_path, workspace_name="default")
    rctx = RequestContext(srv, msg=SimpleNamespace())  # type: ignore[arg-type]
    out = await handle_files_head({"ref": "character_photo:hiro"}, rctx)

    assert out == {
        "blob_id": expected_blob,
        "size": expected_size,
        "media_type": media_type,
        "chunk_size": DEFAULT_CHUNK_SIZE,
        "chunk_count": expected_chunks,
    }


@pytest.mark.asyncio
async def test_files_head_missing_ref_raises() -> None:
    srv = SimpleNamespace(workspace_path=None, workspace_name="default")
    rctx = RequestContext(srv, msg=SimpleNamespace())  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="ref is required"):
        await handle_files_head({}, rctx)
