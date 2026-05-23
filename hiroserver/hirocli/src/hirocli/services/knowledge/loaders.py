"""File loaders registered by extension for knowledge ingest."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from hirocli.services.knowledge.chunker import chunk_markdown, markdown_chunk_error, title_from_markdown
from hirocli.services.knowledge.models import LoadedKnowledgeDocument


class KnowledgeLoader(Protocol):
    extensions: frozenset[str]

    def load(
        self,
        path: Path,
        data: bytes,
        *,
        chunk_size: int,
        chunk_overlap: int,
        respect_headings: bool,
    ) -> LoadedKnowledgeDocument:
        """Load bytes into knowledge chunks and document metadata."""


class MarkdownLoader:
    extensions = frozenset({".md"})

    def load(
        self,
        path: Path,
        data: bytes,
        *,
        chunk_size: int,
        chunk_overlap: int,
        respect_headings: bool,
    ) -> LoadedKnowledgeDocument:
        text = data.decode("utf-8-sig")
        chunks = chunk_markdown(
            text,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            respect_headings=respect_headings,
        )
        if not chunks:
            message = markdown_chunk_error(path, text, respect_headings=respect_headings)
            raise ValueError(message or f"No text chunks produced from {path}.")
        return LoadedKnowledgeDocument(
            title=title_from_markdown(text, path),
            mime="text/markdown",
            chunks=chunks,
        )


class LoaderRegistry:
    def __init__(self, loaders: Sequence[KnowledgeLoader] = ()) -> None:
        self._loaders: dict[str, KnowledgeLoader] = {}
        for loader in loaders:
            self.register(loader)

    def register(self, loader: KnowledgeLoader) -> None:
        for ext in loader.extensions:
            clean = ext.lower()
            if not clean.startswith("."):
                raise ValueError(f"Loader extension must start with '.': {ext}")
            self._loaders[clean] = loader

    def resolve(self, ext: str) -> KnowledgeLoader | None:
        return self._loaders.get(ext.lower())

    @property
    def extensions(self) -> frozenset[str]:
        return frozenset(self._loaders)


DEFAULT_LOADER_REGISTRY = LoaderRegistry([MarkdownLoader()])
SUPPORTED_EXTENSIONS = DEFAULT_LOADER_REGISTRY.extensions
