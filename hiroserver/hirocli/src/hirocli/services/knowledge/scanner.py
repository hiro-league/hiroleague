"""Folder enumeration for knowledge ingest source selection."""

from __future__ import annotations

from pathlib import Path

from hirocli.services.knowledge.catalog_store import CatalogStore
from hirocli.services.knowledge.loaders import LoaderRegistry
from hirocli.services.knowledge.models import ScanFolderResult, ScannedFile


class SourceScanner:
    """Enumerate files under a folder for ingest selection."""

    def __init__(self, loader_registry: LoaderRegistry, catalog: CatalogStore) -> None:
        self.loader_registry = loader_registry
        self.catalog = catalog

    def scan(self, root: Path, *, recursive: bool = True) -> ScanFolderResult:
        pattern = "**/*" if recursive else "*"
        known = self.catalog.known_source_uris()
        files: list[ScannedFile] = []
        for path in sorted(p for p in root.glob(pattern) if p.is_file()):
            ext = path.suffix.lower()
            supported = self.loader_registry.resolve(ext) is not None
            files.append(
                ScannedFile(
                    path=str(path),
                    relative_path=str(path.relative_to(root)),
                    ext=ext,
                    size_bytes=path.stat().st_size,
                    supported=supported,
                    already_ingested=str(path.resolve()) in known,
                    disabled_reason=None if supported else f"Unsupported extension: {ext or '(none)'}",
                )
            )
        return ScanFolderResult(root=str(root), files=files)
