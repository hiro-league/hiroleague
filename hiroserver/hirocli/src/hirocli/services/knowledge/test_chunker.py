from __future__ import annotations

from pathlib import Path

import pytest

from hirocli.services.knowledge.chunker import markdown_chunk_error
from hirocli.services.knowledge.loaders import MarkdownLoader


def test_markdown_chunk_error_empty_file() -> None:
    path = Path("empty.md")
    message = markdown_chunk_error(path, "   \n  ", respect_headings=True)
    assert message is not None
    assert message.startswith("No extractable text in markdown file:")
    assert message.endswith("empty.md")


def test_markdown_loader_raises_clear_error_for_empty_markdown(tmp_path: Path) -> None:
    path = tmp_path / "empty.md"
    path.write_text("   \n\t  ", encoding="utf-8")
    loader = MarkdownLoader()
    with pytest.raises(ValueError, match="No extractable text in markdown file"):
        loader.load(path, path.read_bytes(), chunk_size=200, chunk_overlap=20, respect_headings=True)
