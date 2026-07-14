from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

# Version from this package's own installed metadata (source of truth =
# pyproject.toml); stdlib-only, no sibling-package import.
try:
    __version__ = _pkg_version("hiro-channel-devices")
except PackageNotFoundError:  # raw source tree, not installed
    __version__ = "0.0.0+unknown"
