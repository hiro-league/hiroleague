"""hirogateway — WebSocket relay gateway."""

from hiro_commons.version import package_version

# Read from installed metadata so it can never drift from pyproject.toml.
__version__ = package_version("hirogate")
