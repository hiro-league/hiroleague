"""Shared commons utilities for Hiro workspace packages."""

from .llm_usage import (
    coerce_positive_int,
    gemini_usage_aggregate_fallback,
    modality_token_count,
)
from .log import Logger
from .nonces import generate_nonce
from .timestamps import parse_iso8601_utc, utc_iso, utc_now
from .version import package_version

# Read from installed metadata so it can never drift from pyproject.toml.
__version__ = package_version("hiro-commons")

__all__ = [
    "Logger",
    "coerce_positive_int",
    "gemini_usage_aggregate_fallback",
    "generate_nonce",
    "modality_token_count",
    "package_version",
    "parse_iso8601_utc",
    "utc_iso",
    "utc_now",
]
