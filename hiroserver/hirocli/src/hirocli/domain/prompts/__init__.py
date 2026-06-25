"""Bundled default prompt texts, stored as markdown and loaded from the package.

Mirrors ``hirocli.catalog_data`` (catalog.yaml): the prompt *content* lives in data files,
not in Python source. The IDs/registry and runtime composition stay in ``preferences.py`` —
only the prose moved here. Editable as plain markdown (the admin Preferences UI authors these
fields as markdown), with no Python string-escaping.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from importlib import resources

logger = logging.getLogger(__name__)

_PACKAGE = "hirocli.domain.prompts"


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """Return the text of the bundled default prompt ``<name>.md`` (read once, then cached).

    Uses ``importlib.resources`` so it works when installed as a wheel — the same mechanism as
    the bundled model catalog. A missing/unreadable file raises with context so a broken build
    fails loudly at import instead of silently falling back to an empty prompt.
    """
    try:
        return resources.files(_PACKAGE).joinpath(f"{name}.md").read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as exc:
        logger.error("❌ Failed to load default prompt — %s · %s", name, exc, exc_info=True)
        raise RuntimeError(f"Missing or unreadable default prompt file: {name}.md") from exc
