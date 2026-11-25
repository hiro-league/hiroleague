"""The right each of Hiro's tools needs, and the person a turn acts for (Permissions phase 4).

Hiro acts as the person it talks to: every tool it can run names one core permission (``domain/core_features.py``,
the source ``hiroleague``), and a turn's tool calls are held to that person's rights through the SDK's one check, their
roles adding up. Only Hiro's path is held (``langchain_adapter.py``): the command line, the control server's
``/invoke``, the admin's routes and the devices' requests call the same tools as the owner, or check on their own.

- **A tool names its right** (``Tool.right``): a :class:`ToolRight`, or :data:`OWNER_ONLY` for what no core feature
  covers (people and roles, which are the owner's; a send to people on WhatsApp). The contract test
  (``tools/tests/test_tool_rights.py``) fails for an agent tool that names none.
- **A right about people's things says whose the record is** before the tool runs:
  - :data:`BY_RECORD`: the tool's ``record_users(workspace_path, **params)`` names the chat users the record belongs
    to; a grant for their own things passes only when the person is one of them, else the record answers as not
    found;
  - :data:`THEIRS`: the tool takes ``acting`` and answers for that person's things: a list kept to the reach, or an
    act on their own (a new conversation of theirs, their memory).
- **A tool the person may not use is never offered** to the model (:func:`may_use`), and is refused again when it is
  called (:func:`hold`), with words the model passes on.
- **Hiro works in its own workspace:** a tool's ``workspace`` parameter is never offered to the model, and the tool
  is handed the workspace the turn runs in: its path, or its id in the registry for a tool that takes only a name.

Pure but for the family list: :func:`acting_for` reads the person's roles.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from hiro_channel_sdk.access import Reach, reach

if TYPE_CHECKING:
    from .base import Tool

Whose = Literal["", "by_record", "theirs"]
BY_RECORD: Whose = "by_record"
THEIRS: Whose = "theirs"

# The parameter every workspace-scoped tool takes, never offered to Hiro's model: Hiro works where it runs.
WORKSPACE_PARAM = "workspace"


@dataclass(frozen=True)
class ToolRight:
    """The one core permission a tool needs: ``feature`` (``logs``, ``ai.providers``) and its ``action`` (``see``).
    ``whose`` is set for a right about people's things (a personal right): where the record's person comes from."""

    feature: str
    action: str
    whose: Whose = ""

    @property
    def key(self) -> str:
        return f"{self.feature}.{self.action}" if self.feature else "the owner's"


# What no core feature covers: only the owner's turns use it.
OWNER_ONLY = ToolRight("", "")


@dataclass(frozen=True)
class Acting:
    """The person a turn acts for: who wrote it (the inbound check's writer), their chat user (whose conversations and
    memory are theirs), and each role they hold with its keys in the core, which the one check adds up."""

    person_id: str  # "" = no family list yet: the owner
    name: str
    user_id: int
    owner: bool
    workspace_path: Path
    roles: Mapping[str, list[str]] = field(default_factory=dict)
    workspace_id: str | None = None  # its id in the registry, for a tool that takes a workspace's name

    def reach(self, right: ToolRight) -> Reach:
        """How far this person reaches for a tool's right: "all", "own" (a grant for their own things) or "no"."""
        if self.owner:
            return "all"
        if right == OWNER_ONLY:
            return "no"
        from ..domain.core_features import CORE_BY_ID

        return reach(self.roles, right.feature, right.action, CORE_BY_ID)


class ToolRefused(Exception):
    """A tool call the turn's person may not make: ``words`` are for the model to pass on, ``reason`` for the log
    (``no_right``, ``not_theirs``, ``nobody``)."""

    def __init__(self, words: str, reason: str) -> None:
        super().__init__(words)
        self.words = words
        self.reason = reason


_ACTING: ContextVar[Acting | None] = ContextVar("hiro_acting_for", default=None)


def begin(acting: Acting) -> Token[Acting | None]:
    """From here, every tool Hiro runs is held to ``acting``'s rights (the agent manager, as a turn starts); hand the
    token to :func:`end` when it ends."""
    return _ACTING.set(acting)


def end(token: Token[Acting | None]) -> None:
    _ACTING.reset(token)


@contextmanager
def acting_as(acting: Acting) -> Iterator[None]:
    """Hold every tool Hiro runs inside this block to ``acting``'s rights."""
    token = begin(acting)
    try:
        yield
    finally:
        end(token)


def current() -> Acting | None:
    """The person the running turn acts for; None outside a turn."""
    return _ACTING.get()


def right_of(tool: "Tool") -> ToolRight | None:
    return type(tool).right


def may_use(acting: Acting, tool: "Tool") -> bool:
    """Whether ``acting`` may use ``tool`` at all: its right reaches their own things at least. A tool that names no
    right answers the owner only."""
    right = right_of(tool) or OWNER_ONLY
    return acting.reach(right) != "no"


def _accepts(fn: Any, name: str) -> bool:
    try:
        return name in inspect.signature(fn).parameters
    except (TypeError, ValueError):  # a builtin or a callable inspect can't read: hand it nothing extra
        return False


def entry(tool: "Tool") -> Any:
    """The callable Hiro's adapter runs: ``execute_async`` when the tool has one, else ``execute``."""
    exec_async = getattr(tool, "execute_async", None)
    return exec_async if callable(exec_async) else tool.execute


def hold(tool: "Tool", kwargs: dict[str, Any]) -> dict[str, Any]:
    """The arguments a tool runs with on Hiro's path, held to the turn's person; else :class:`ToolRefused`.

    The model's ``workspace`` goes (the turn's own is handed in); a right about people's things checks whose the
    record is (:data:`BY_RECORD`) or hands the tool the person (:data:`THEIRS`)."""
    acting = current()
    if acting is None:
        raise ToolRefused("Hiro can't tell whom this turn is for, so it runs no tool.", "nobody")
    right = right_of(tool) or OWNER_ONLY
    got = acting.reach(right)
    if got == "no":
        what = "only the owner can" if right == OWNER_ONLY else f"it needs {right.key}"
        raise ToolRefused(f"{acting.name} may not use {tool.name}: {what}.", "no_right")
    held = {k: v for k, v in kwargs.items() if k != WORKSPACE_PARAM}
    fn = entry(tool)
    if _accepts(fn, "workspace_path"):
        held["workspace_path"] = acting.workspace_path
    elif WORKSPACE_PARAM in tool.params and acting.workspace_id:
        held[WORKSPACE_PARAM] = acting.workspace_id
    if right.whose == BY_RECORD and got == "own":
        params = {k: v for k, v in held.items() if k != "workspace_path"}
        users = tool.record_users(acting.workspace_path, **params)  # type: ignore[attr-defined]
        if acting.user_id not in users:
            # Another person's record answers as a missing one (as a device's request does)
            raise ToolRefused(f"{tool.name}: no such record for {acting.name}.", "not_theirs")
    if right.whose == THEIRS:
        held["acting"] = acting
    return held


def acting_for(workspace_path: Path, *, person_id: str, name: str, user_id: int, owner: bool) -> Acting:
    """The person a turn acts for, from the writer the inbound check stamped on it: their roles' keys in the core.
    ``person_id`` "" is the owner with no family list yet."""
    from ..domain.access import admin_access
    from ..domain.people import get_person

    roles: dict[str, list[str]] = {}
    if person_id:
        person = get_person(workspace_path, person_id)
        if person is not None:
            roles = dict(admin_access(workspace_path, person.role_ids).roles)
    return Acting(person_id=person_id, name=name or "this person", user_id=user_id, owner=owner,
                  workspace_path=workspace_path, roles=roles, workspace_id=workspace_id_of(workspace_path))


def workspace_id_of(workspace_path: Path) -> str | None:
    """The registry's id for the workspace at ``workspace_path``; None when the registry doesn't list it (a test's)."""
    from ..domain.workspace import WorkspaceError, load_registry

    try:
        registry = load_registry()
    except (OSError, ValueError, WorkspaceError):  # no registry to read: the tool's own default stands
        return None
    want = workspace_path.resolve()
    return next((wid for wid, e in registry.workspaces.items() if Path(e.path).resolve() == want), None)
