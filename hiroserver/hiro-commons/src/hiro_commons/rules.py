"""Every route's rule: who may call it and, for a permission about people's things, whose the record is. One shape and
one matching for the backend kit's route check (every app's `Extension.rules`) and the core admin's (Permissions, the
design's §5 and §8). Pure: dataclasses only.

Who may call a route:

- `public`: everyone (the checks, signing in, what reports in with its own key);
- `signed_in`: anyone with a role (the live notices every page listens to);
- `owner`: owners only (people, roles and grants);
- `features`: someone whose roles hold the permission in one of the rule's features. Reading (GET) needs "see"; any
  change needs the feature's first action after "see", unless the rule names the action.

A permission is `<feature>.<action>`; a feature's id carries its area when an area groups several features
(`ai.providers.change`). **Never find a feature's keys by prefix:** `logs` beside `logs.runs` would catch the other
feature's keys. Build them from the declared features and actions instead.

Whose a record is (`Rule.whose`), for an action declared personal (granted for the person's own things or for
everyone's). A grant for everyone's passes without it. A grant for their own passes only through it:

- `by_person(param)`: a person's id is in the path or the query, compared with the asker;
- `by_lookup(name, param)`: a record's id is in `param`; the lookup registered under `name` gives its people, and the
  asker must be one of them;
- `LIST`: the handler is handed the reach ("own" or "all") and filters by it.

With no `whose` under a personal action, only a grant for everyone's passes. Each side keeps its own list of rules, its
own registry of lookups and its own runner; both runners ask the SDK's one check (`hiro_channel_sdk.access`).

A route with no rule answers the owner only: a new route is never open by accident. First match wins, so exact paths and
narrow prefixes come before wide ones.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

Who = Literal["public", "signed_in", "owner", "features"]
WhoseKind = Literal["param", "lookup", "list"]


@dataclass(frozen=True)
class Whose:
    """Where a record's person comes from, for a route under a personal action."""

    kind: WhoseKind
    param: str = ""  # "param": the parameter holding the person's id; "lookup": the one holding the record's id
    lookup: str = ""  # "lookup": the name its lookup is registered under (a record's id -> its people)


def by_person(param: str) -> Whose:
    """The person's id is the path or query parameter `param`."""
    if not param:
        raise ValueError("by_person needs the parameter that holds the person's id")
    return Whose("param", param=param)


def by_lookup(name: str, param: str) -> Whose:
    """The record's id is the path or query parameter `param`; the lookup registered as `name` gives its people."""
    if not name or not param:
        raise ValueError("by_lookup needs the lookup's name and the parameter that holds the record's id")
    return Whose("lookup", param=param, lookup=name)


LIST = Whose("list")  # a list of records: the handler is handed the reach and filters by it


@dataclass(frozen=True)
class Rule:
    path: str  # a route's path, or the start of several ("/api/logs" covers /api/logs/...)
    who: Who = "features"
    features: tuple[str, ...] = ()
    methods: tuple[str, ...] = ()  # only for these methods; none: every method
    action: str | None = None  # None: "see" to read, else the feature's first action after "see"
    whose: Whose | None = None  # where a record's person comes from, under a personal action


def for_features(path: str, *features: str, methods: Sequence[str] = (), action: str | None = None,
                 whose: Whose | None = None) -> Rule:
    """A rule open to someone whose roles hold the permission in any of `features`."""
    return Rule(path, "features", tuple(features), tuple(methods), action, whose)


def matches(rule: Rule, method: str, path: str) -> bool:
    """Whether a rule covers a request: its methods (a HEAD is a GET), and its path or a path under it by whole parts
    (`/api/logs` covers `/api/logs/today`, not `/api/logsx`)."""
    method = "GET" if method == "HEAD" else method
    if rule.methods and method not in rule.methods:
        return False
    return path == rule.path or path.startswith(rule.path + "/")


def rule_for(rules: Iterable[Rule], method: str, path: str) -> Rule | None:
    """The first rule that covers a request (its path as declared, e.g. /api/items/{item_id}), or None."""
    return next((r for r in rules if matches(r, method, path)), None)
