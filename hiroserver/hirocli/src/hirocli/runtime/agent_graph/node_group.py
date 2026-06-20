"""NodeGroup — base class for cohesive agent graph node groups."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...domain.preferences import DEFAULT_MAX_HISTORY_MESSAGES
from .ledger import wrap_graph_node
from .preferences_view import PreferencesView

if TYPE_CHECKING:
    from .services import AgentServices

TRIMMED_MESSAGE_LIMIT = DEFAULT_MAX_HISTORY_MESSAGES


def _is_graph_node_method(name: str, attr: Any) -> bool:
    if name.startswith("_") or not callable(attr):
        return False
    return name.endswith("_node") or name.startswith("node_")


def _node_label(name: str) -> str:
    if name.endswith("_node"):
        return name[: -len("_node")]
    if name.startswith("node_"):
        return name[len("node_") :]
    return name


class NodeGroup:
    """Owns ledger plumbing and shared preference accessors for node groups."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        seen: set[str] = set()
        for base in reversed(cls.mro()[1:]):
            for name, attr in getattr(base, "__dict__", {}).items():
                if name in seen or not _is_graph_node_method(name, attr):
                    continue
                seen.add(name)
                setattr(cls, name, wrap_graph_node(_node_label(name), attr))
        for name, attr in list(cls.__dict__.items()):
            if _is_graph_node_method(name, attr):
                setattr(cls, name, wrap_graph_node(_node_label(name), attr))

    def __init__(self, services: "AgentServices") -> None:
        self.services = services
        self._ledger_sink = services.ledger_sink
        self.prefs = PreferencesView(services.preferences, services.workspace_path)

    def _wrap_dynamic_node(self, node_name: str, fn):
        from .ledger import wrap_graph_callable

        return wrap_graph_callable(self, node_name, fn)
