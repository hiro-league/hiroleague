"""Every route's rule, as an app lists them (`Extension.rules`, its extension.py): who may call it. Pure.

- `public`: everyone (the checks, signing in, what reports in with its own key);
- `signed_in`: anyone with a role (the live notices every page listens to);
- `owner`: owners only (users and roles);
- `features`: a role with the right in one of the rule's features. Reading (GET) needs "see"; any change needs the
  feature's first right after "see", unless the rule names the right.

A route with no rule is refused for everyone but the owner and sign-in off: a new route is never open by accident, and
each app's tests/test_guard.py fails until it has one. First match wins: exact paths and narrow prefixes before wide
ones.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

Who = Literal["public", "signed_in", "owner", "features"]


@dataclass(frozen=True)
class Rule:
    path: str  # a route's path, or the start of several ("/api/logs" covers /api/logs/...)
    who: Who = "features"
    features: tuple[str, ...] = ()
    methods: tuple[str, ...] = ()  # only for these methods; none: every method
    right: str | None = None  # None: "see" to read, else the feature's main right


def for_features(path: str, *features: str, methods: Sequence[str] = (), right: str | None = None) -> Rule:
    """A rule open to a role with the right in any of `features`."""
    return Rule(path, "features", tuple(features), tuple(methods), right)
