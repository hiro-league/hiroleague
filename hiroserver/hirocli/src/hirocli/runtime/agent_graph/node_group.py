"""NodeGroup — base class for cohesive agent graph node groups."""

from __future__ import annotations

from collections.abc import Callable
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


def _full_label(prefix: str, method_name: str) -> str:
    """Compose the ledger row label: ``"{prefix}/{node_label}"`` when prefix is set, else bare."""
    base = _node_label(method_name)
    return f"{prefix}/{base}" if prefix else base


class NodeGroup:
    """Owns ledger plumbing and shared preference accessors for node groups.

    Subclasses may set ``_ledger_label_prefix`` to namespace ledger row ``node`` values
    (e.g. ``"knowledge"`` → ``"knowledge/parse_query"``). The prefix is a LEDGER label only —
    the LangGraph routing name (the first arg passed to ``StateGraph.add_node``) stays bare.
    Namespacing matters when (a) the admin UI groups rows by prefix
    (``graph-runs-pure.isGraphNodeSubstep`` keys on ``knowledge/``), and (b) two groups would
    otherwise share a node name (e.g. chat ``call_model`` vs knowledge ``call_model``) and
    collide in ``LedgerSink``'s per-(run, node) attempt/step counters and ``RunAccumulator``'s
    ``node == "call_model"`` model-stamping check.
    """

    _ledger_label_prefix: str = ""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        prefix = (getattr(cls, "_ledger_label_prefix", "") or "").strip("/")
        seen: set[str] = set()
        for base in reversed(cls.mro()[1:]):
            for name, attr in getattr(base, "__dict__", {}).items():
                if name in seen or not _is_graph_node_method(name, attr):
                    continue
                seen.add(name)
                setattr(cls, name, wrap_graph_node(_full_label(prefix, name), attr))
        for name, attr in list(cls.__dict__.items()):
            if _is_graph_node_method(name, attr):
                setattr(cls, name, wrap_graph_node(_full_label(prefix, name), attr))

    def __init__(self, services: "AgentServices") -> None:
        self.services = services
        self.prefs = PreferencesView(services.preferences, services.workspace_path)

    @property
    def _ledger_sink(self):
        """Always read the live sink from ``AgentServices`` (tests + hot-swap)."""
        return self.services.ledger_sink

    @_ledger_sink.setter
    def _ledger_sink(self, sink) -> None:
        self.services.ledger_sink = sink

    def _wrap_dynamic_node(self, node_name: str, fn):
        from .ledger import wrap_graph_callable

        return wrap_graph_callable(self, node_name, fn)

    @classmethod
    def node_methods(cls) -> dict[str, str]:
        """Map LangGraph node label → bound method attribute name for every ``*_node`` / ``node_*``."""
        out: dict[str, str] = {}
        for base in cls.mro():
            for name, attr in getattr(base, "__dict__", {}).items():
                if _is_graph_node_method(name, attr):
                    out.setdefault(_node_label(name), name)
        order = getattr(cls, "_NODE_REGISTRATION_ORDER", None)
        if not order:
            return out
        ordered: dict[str, str] = {}
        for label in order:
            if label in out:
                ordered[label] = out[label]
        for label, name in out.items():
            if label not in ordered:
                ordered[label] = name
        return ordered

    def registered_nodes(self) -> dict[str, Callable[..., Any]]:
        """Bound node callables keyed by LangGraph node label (insertion order preserved)."""
        return {label: getattr(self, name) for label, name in type(self).node_methods().items()}
