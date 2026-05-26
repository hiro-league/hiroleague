from __future__ import annotations

from pathlib import Path

import pytest

from hirocli.services.knowledge.chunker import embed_text_for_chunk, markdown_chunk_error
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


def test_embed_text_prefixes_breadcrumb_without_duplicating_title() -> None:
    # Title is derived from the H1, which heading_path already starts with → no duplication,
    # and the markdown hashes are stripped for the embedded text.
    chunk = {
        "text": "Unused days expire after March 31.",
        "heading_path": "# Employee Handbook / ## Leave Policy / ### Annual Leave / #### Carryover Rules",
    }
    text = embed_text_for_chunk("Employee Handbook", chunk)
    assert text == (
        "Employee Handbook / Leave Policy / Annual Leave / Carryover Rules\n"
        "Unused days expire after March 31."
    )
    assert "#" not in text.split("\n", 1)[0]
    assert text.count("Employee Handbook") == 1


def test_embed_text_adds_breadcrumb_to_headingless_continuation_chunk() -> None:
    # A continuation/overlap piece keeps the section's heading_path but its body has no
    # heading line — it must still gain the full breadcrumb.
    chunk = {"text": "…continues mid-sentence about accrual…", "heading_path": "# Doc / ## Section"}
    assert embed_text_for_chunk("Doc", chunk).startswith("Doc / Section\n")


def test_embed_text_prepends_title_when_absent_from_heading_path() -> None:
    # No H1 → title is the filename stem and is absent from heading_path, so it leads.
    chunk = {"text": "body", "heading_path": "## Section"}
    assert embed_text_for_chunk("my-notes", chunk) == "my-notes / Section\nbody"


def test_embed_text_title_only_when_no_heading_path() -> None:
    # respect_headings=False (or a heading-less doc) → no heading_path, title still embedded.
    chunk = {"text": "body", "heading_path": None}
    assert embed_text_for_chunk("my-notes", chunk) == "my-notes\nbody"


def test_embed_text_returns_body_when_no_title_or_headings() -> None:
    chunk = {"text": "body", "heading_path": None}
    assert embed_text_for_chunk("", chunk) == "body"
    assert embed_text_for_chunk(None, chunk) == "body"
