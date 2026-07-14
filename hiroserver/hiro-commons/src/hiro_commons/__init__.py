"""Shared commons utilities for Hiro workspace packages."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

from .llm_usage import (
    coerce_positive_int,
    gemini_usage_aggregate_fallback,
    modality_token_count,
)
from .log import Logger
from .nonces import generate_nonce
from .timestamps import parse_iso8601_utc, utc_iso, utc_now

# Version from this package's own installed metadata (source of truth =
# pyproject.toml); stdlib-only and self-referential, so importing this package
# never depends on a sibling package being present.
try:
    __version__ = _pkg_version("hiro-commons")
except PackageNotFoundError:  # raw source tree, not installed
    __version__ = "0.0.0+unknown"

__all__ = [
    "Logger",
    "coerce_positive_int",
    "gemini_usage_aggregate_fallback",
    "generate_nonce",
    "modality_token_count",
    "parse_iso8601_utc",
    "utc_iso",
    "utc_now",
]
