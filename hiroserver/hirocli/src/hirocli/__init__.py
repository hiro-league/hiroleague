"""Hiro desktop server package."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

# Version from this package's own installed metadata (source of truth =
# pyproject.toml). Stdlib-only and self-referential: `hiro` (incl. `hiro stop`)
# still imports even if a sibling package like hiro_commons is missing from a
# half-synced venv — the recovery command must not depend on what it recovers.
try:
    __version__ = _pkg_version("hirocli")
except PackageNotFoundError:  # raw source tree, not installed
    __version__ = "0.0.0+unknown"
