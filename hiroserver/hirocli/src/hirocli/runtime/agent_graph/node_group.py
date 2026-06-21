"""NodeGroup — base class for cohesive agent graph node groups."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from langgraph.graph import StateGraph
from langgraph.types import RetryPolicy

from ...domain.preferences import DEFAULT_MAX_HISTORY_MESSAGES
from .ledger import wrap_graph_node
from .preferences_view import PreferencesView

if TYPE_CHECKING:
    from .services import AgentServices

TRIMMED_MESSAGE_LIMIT = DEFAULT_MAX_HISTORY_MESSAGES


def mount(graph: StateGraph, group: "NodeGroup") -> None:
    """Register every active node from ``group``, attaching its declared retry policy.

    Lives here (not in ``chat.py``) so the knowledge graph builder can reuse it without
    importing the chat package — that direction is a circular import via the shared
    ``GraphState`` → ``services.knowledge.models`` chain.
    """
    for label, fn in group.registered_nodes().items():
        kwargs: dict = {}
        if (retry := group.retry_policy_for(label)) is not None:
            kwargs["retry_policy"] = retry
        graph.add_node(label, fn, **kwargs)


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
    # Per-node retry policy. Builder applies these to ``StateGraph.add_node`` so retry
    # config lives with the node group that owns the node, not in the graph builder.
    _RETRY_POLICIES: dict[str, RetryPolicy] = {}

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
        """Bound node callables keyed by LangGraph node label (insertion order preserved).

        Filters out labels for which ``is_active(label)`` returns False, so the graph
        builder no longer has to maintain a parallel skip-set for feature-gated nodes.
        """
        return {
            label: getattr(self, name)
            for label, name in type(self).node_methods().items()
            if self.is_active(label)
        }

    def is_active(self, label: str) -> bool:
        """Whether ``label`` should be registered into the graph by the builder.

        Default True. Subclasses override to feature-gate nodes against bound
        config/services without leaking that decision into the builder
        (e.g. ``LLMNodes`` gates ``tools``; ``KnowledgeFanoutNodes`` gates ``knowledge_retrieve``).
        """
        return True

    def retry_policy_for(self, label: str) -> RetryPolicy | None:
        """Retry policy for ``label``, or None when the node should run with default policy."""
        return self._RETRY_POLICIES.get(label)
