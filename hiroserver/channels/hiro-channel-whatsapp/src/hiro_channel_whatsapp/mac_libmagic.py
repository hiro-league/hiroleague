"""libmagic on a Mac, for neonize: imported before neonize, which imports python-magic as it loads.

python-magic needs the libmagic library on the machine: Linux ships it and Windows takes python-magic-bin (it bundles
the DLL), but macOS has none unless Homebrew's ``libmagic`` is installed, so the plugin didn't even start
(``ImportError: failed to find libmagic``). pylibmagic (a Mac-only dependency) carries libmagic and its database for
Apple's chips and Intel; importing it points python-magic's loader at them (DYLD_LIBRARY_PATH and MAGIC, in this
process). Elsewhere nothing changes.
"""

from __future__ import annotations

import sys


def load() -> bool:
    """Make the bundled libmagic findable on a Mac; True when it was loaded (a Mac), False elsewhere."""
    if sys.platform != "darwin":
        return False
    import pylibmagic  # noqa: F401  (importing it is the work: it sets this process's library and database paths)

    return True


load()
