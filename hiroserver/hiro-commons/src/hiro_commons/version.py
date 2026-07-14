"""Single source of truth for package ``__version__`` across the workspace.

Each Hiro package version lives only in its ``pyproject.toml``. Reading it back
at runtime from the installed distribution metadata means ``__version__`` can
never drift from the published version again — no hand-edited literal to forget.
Usage in a package ``__init__``::

    from hiro_commons.version import package_version

    __version__ = package_version("hiro-commons")
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _dist_version

__all__ = ["package_version"]


def package_version(distribution_name: str) -> str:
    """Installed version of ``distribution_name`` from its metadata.

    Falls back to ``"0.0.0+unknown"`` when the distribution isn't installed
    (e.g. imported from a raw source tree that was never installed), so an
    import-time ``__version__ = package_version(...)`` never raises.
    """
    try:
        return _dist_version(distribution_name)
    except PackageNotFoundError:
        return "0.0.0+unknown"
