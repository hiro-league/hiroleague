"""Hiro desktop server package."""

from hiro_commons.version import package_version

# Read from installed metadata so it can never drift from pyproject.toml.
__version__ = package_version("hirocli")
