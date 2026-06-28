"""Local (in-process) knowledge embedder registry — the non-catalog analog of the model catalog.

Cloud embedders (OpenAI, …) live in ``catalog.yaml`` and resolve through the model factory. Local
FastEmbed embedders are in-process ONNX models with no API key and no provider endpoint, so — like
the local rerankers (see ``reranker_registry``) — they are NOT catalog rows. They live here, keyed
by their FastEmbed ``sentence-transformers/<name>`` id so ``resolve_knowledge_embedder`` builds the
FastEmbed lane directly from the stored id.

Embedders are mandatory + dimension-bound, so the registry carries each model's vector ``dimension``
for the picker. Download status is tracked with the shared marker scheme (``download_markers``); the
FastEmbed backend also writes that marker on first real use, so auto-download-on-ingest and an
explicit pre-download converge on the same "downloaded" signal.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from hiro_commons.log import Logger

from hirocli.services.knowledge.constants import KNOWLEDGE_DIR

log = Logger.get("SVC.KNOWLEDGE.EMBED")

# Local FastEmbed embedders download into the shared dense cache (same dir the FastEmbed backend
# uses at ingest), so an explicit download and an ingest-triggered one share one cache + marker.
FASTEMBED_CACHE_DIR = "fastembed_cache"


@dataclass(frozen=True)
class LocalEmbedderSpec:
    """A local in-process FastEmbed embedder option (registry analog of a catalog ModelSpec)."""

    id: str  # FastEmbed ``sentence-transformers/<name>`` id — resolved by the FastEmbed lane.
    display_name: str
    size_label: str
    dimension: int
    languages: str
    multilingual: bool
    description: str = ""


# Curated local options. ids are real FastEmbed model names so resolution needs no mapping.
LOCAL_EMBEDDERS: tuple[LocalEmbedderSpec, ...] = (
    LocalEmbedderSpec(
        id="sentence-transformers/all-MiniLM-L6-v2",
        display_name="all-MiniLM-L6-v2 (FastEmbed)",
        size_label="~90 MB",
        dimension=384,
        languages="English",
        multilingual=False,
        description="Small, fast English-only embedder. Good default for English-only corpora.",
    ),
    LocalEmbedderSpec(
        id="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        display_name="paraphrase-multilingual-MiniLM-L12-v2 (FastEmbed)",
        size_label="~470 MB",
        dimension=384,
        languages="multilingual (50+)",
        multilingual=True,
        description="Compact multilingual embedder (incl. Arabic). Balanced size/quality.",
    ),
    LocalEmbedderSpec(
        id="sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
        display_name="paraphrase-multilingual-mpnet-base-v2 (FastEmbed)",
        size_label="~1.1 GB",
        dimension=768,
        languages="multilingual (50+)",
        multilingual=True,
        description="Larger multilingual embedder — best local quality, higher cost/latency.",
    ),
)

_BY_ID: dict[str, LocalEmbedderSpec] = {spec.id: spec for spec in LOCAL_EMBEDDERS}


def list_local_embedders() -> list[LocalEmbedderSpec]:
    return list(LOCAL_EMBEDDERS)


def get_local_embedder(model_id: str) -> LocalEmbedderSpec | None:
    return _BY_ID.get((model_id or "").strip())


def is_local_embedder(model_id: str) -> bool:
    return (model_id or "").strip() in _BY_ID


def embedder_cache_dir(workspace_path: Path) -> Path:
    return Path(workspace_path) / KNOWLEDGE_DIR / FASTEMBED_CACHE_DIR


def is_downloaded(spec: LocalEmbedderSpec, cache_dir: Path) -> bool:
    """True when this embedder's weights were downloaded/loaded into ``cache_dir`` before."""
    from hirocli.services.knowledge.download_markers import is_marked

    return is_marked(cache_dir, spec.id)


def download(spec: LocalEmbedderSpec, cache_dir: Path) -> None:
    """Explicitly fetch a local embedder's weights into ``cache_dir`` (blocking).

    Instantiates FastEmbed once (which performs the download), then writes the marker. Any failure
    propagates with a logged error and leaves no marker, so the model stays "not downloaded".
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        from fastembed import TextEmbedding

        TextEmbedding(model_name=spec.id, cache_dir=str(cache_dir))
    except Exception:
        log.error(
            "❌ Embedder download failed — HiroServer · %s",
            spec.id,
            size=spec.size_label,
            exc_info=True,
        )
        raise
    from hirocli.services.knowledge.download_markers import write_marker

    write_marker(cache_dir, spec.id, content=spec.id)
    log.info("✅ Embedder downloaded — HiroServer · %s", spec.id, size=spec.size_label)
