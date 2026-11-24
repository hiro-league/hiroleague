"""Whose a record is, for a route under an action declared personal (granted for the person's own things or for
everyone's). The route's rule names where the record's person comes from (`hiro_commons.rules.Whose`); the route check
(guard.py) settles it before the handler runs, so no handler has to remember it.

- `by_person(param)`: nothing to register; the guard compares the parameter with the asker.
- `by_lookup(name, param)`: the app registers here what turns a record's id into its people, once, where the feature's
  store lives:

      whose.register("device", lambda session, device_id: people_of_device(session, device_id))

  A record nobody owns, or one that doesn't exist, has no people: a grant for their own things doesn't reach it.
- `LIST`: the handler takes the reach the guard settled, and filters by it:

      @router.get("/api/devices")
      def devices(reach: Reach = Depends(listed)) -> list[DeviceOut]: ...

The contract test fails for a personal action whose rule names no whose, a lookup nobody registered, and a list route
that doesn't take the reach.
"""

from collections.abc import Callable, Iterable

from fastapi import Request
from hiro_channel_sdk.access import Reach
from sqlmodel import Session

Lookup = Callable[[Session, str], Iterable[str]]  # (session, a record's id) -> the people it belongs to

_lookups: dict[str, Lookup] = {}


def register(name: str, lookup: Lookup) -> None:
    """Register the lookup a rule names with `by_lookup(name, ...)`. One name, one lookup."""
    if _lookups.get(name, lookup) is not lookup:
        raise ValueError(f"A lookup named {name!r} is registered already")
    _lookups[name] = lookup


def lookup(name: str) -> Lookup | None:
    return _lookups.get(name)


def listed(request: Request) -> Reach:
    """A dependency for a route whose rule is `LIST`: how far the caller's roles reach, "own" or "all" (the guard
    refused "no"), to filter the list by. Not settled by the guard: "no", so nothing is shown by accident."""
    return getattr(request.state, "reach", "no")
