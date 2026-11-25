"""The key rule: which keys this core accepts for an extension, at install and at pairing (the design's §8).

On top of the SDK's grammar (``hiro_channel_sdk.manifest.key_problem``: ``name`` or ``publisher.name``):

- a bare key is only for one of Hiro League's own extensions, listed here (``HIRO_LEAGUE_OWN``); every other
  extension is ``publisher.name``, so keys from different publishers never collide;
- ``hiroleague`` (the core's own source, under which its admin grants are kept) and any publisher starting with
  ``hiro`` are refused;
- one key, one extension, and the same goes for its dashed form (``acme.weather`` and ``acme-weather`` would share a
  service account and an address), which ``domain.extensions.check_name_free`` checks against the paired records.

Pure: no database, no files.
"""

from __future__ import annotations

from hiro_channel_sdk.manifest import dashed, key_problem, publisher

# The core's own source: its admin grants are kept under it (core_features.CORE_SOURCE)
CORE_KEY = "hiroleague"

# Hiro League's own extensions, the only ones with a bare key: the apps (each one's Extension(name=...)) and the
# channels (the channel catalog's and the core's built-in devices channel). A new Hiro League extension is added here.
HIRO_LEAGUE_OWN = frozenset({"home", "net", "train", "study", "reports", "eval", "whatsapp", "devices"})

# A publisher starting with this is Hiro League's: refused for anyone else
RESERVED_PUBLISHER_PREFIX = "hiro"


def key_refusal(key: str) -> str | None:
    """Why this core refuses ``key``, in words for people, or None when the key rule allows it. Whether another
    extension holds it (or its dashed form) is the records' question, asked after this one."""
    problem = key_problem(key)
    if problem:
        return problem
    if key == CORE_KEY:
        return f"“{key}” is HiroLeague's own name; an extension can't take it."
    owner = publisher(key)
    if owner is None:
        if key in HIRO_LEAGUE_OWN:
            return None
        return (
            f"“{key}” has no publisher: only Hiro League's own extensions have a bare key. Name it publisher.{key} "
            "(for example acme.weather)."
        )
    if owner.startswith(RESERVED_PUBLISHER_PREFIX):
        return f"The publisher “{owner}” is reserved for Hiro League."
    return None


def same_dashed(a: str, b: str) -> bool:
    """Two different keys that would share a service account and an address (``acme.weather``, ``acme-weather``)."""
    return a != b and dashed(a) == dashed(b)
