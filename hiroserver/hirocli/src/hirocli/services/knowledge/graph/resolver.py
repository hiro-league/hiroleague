"""L3 entity resolver — deterministic-first, LLM-only-if-ambiguous.

Implements the **Graphiti resolution ladder** (research §1.3) on top of any
:class:`GraphStore`:

1. **Exact normalized-name match** (deterministic, zero LLM cost):
   - 1 hit → link to that node.
   - >1 hits → ambiguous → escalate to LLM disambiguation.
2. **Entropy gate** — short / low-information names ("Sam", "mom") never trust
   string distance; jump straight to the LLM with substring candidates.
3. **rapidfuzz fuzzy match** over substring candidates (high-entropy names only).
   Above the threshold → link. Below → escalate to LLM.
4. **LLM disambiguation** (optional callable) — picks the matching candidate id,
   or returns None to create a new node.

This is the workhorse that minimizes LLM calls while still solving the
two-Ahmeds collision and alias merging. Designed to be testable without an LLM:
the disambiguator is an injected callable, so tests can pass a deterministic
stub and exercise every branch without network/model dependencies.
"""

from __future__ import annotations

import datetime as dt
import math
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from hiro_commons.log import Logger
from rapidfuzz import fuzz

from .ontology import ExtractedEntity
from .store import GraphNode, GraphStore, normalize_name

log = Logger.get("SVC.KNOWLEDGE.GRAPH.RESOLVE")


# Thresholds — mirror Graphiti's deterministic-first defaults. Tunable, but keep
# them constants so changes are a code review event.
NAME_ENTROPY_THRESHOLD = 1.5          # Shannon entropy over characters
MIN_NAME_LENGTH = 6                   # below this, escalate unless multi-token
MIN_NAME_TOKEN_COUNT = 2              # a 2+ token short name still counts as distinctive
FUZZY_MATCH_THRESHOLD = 90            # rapidfuzz WRatio 0-100 (≈ Graphiti's 0.9 Jaccard)
FUZZY_CANDIDATE_LIMIT = 20            # substring candidates pulled before re-ranking


# A disambiguator is async because the production impl is an LLM call. Tests
# pass a sync function wrapped in an async shim. Returns the matched candidate
# id (str), or None to create a new node.
LLMDisambiguator = Callable[[ExtractedEntity, list[GraphNode]], Awaitable[str | None]]


@dataclass(frozen=True)
class ResolutionResult:
    """What the resolver did — surfaced to the ledger so each ingest reports
    how many mentions hit each branch of the ladder. ``llm_call`` is True only
    when the LLM disambiguator was invoked (the cost signal that matters)."""

    node_id: str
    branch: str  # "exact_link" | "fuzzy_link" | "llm_link" | "created"
    llm_call: bool


def _name_entropy(s: str) -> float:
    """Shannon entropy over the character distribution of ``s`` (bits)."""
    if not s:
        return 0.0
    counts = Counter(s)
    total = len(s)
    return -sum((c / total) * math.log2(c / total) for c in counts.values())


def _is_distinctive_name(normalized: str) -> bool:
    """Distinctive == long enough OR multi-token OR high-entropy.

    Short common names ("dad", "Sam", "mom") fail this and force escalation —
    the entropy gate that prevents the resolver from auto-merging on weak signal
    (research §1.3). Names like "Eiffel Tower" or "New York City" pass and are
    safe for fuzzy matching."""
    if not normalized:
        return False
    tokens = normalized.split()
    if len(normalized) >= MIN_NAME_LENGTH or len(tokens) >= MIN_NAME_TOKEN_COUNT:
        return _name_entropy(normalized) >= NAME_ENTROPY_THRESHOLD
    return False


def _best_fuzzy(name: str, candidates: list[GraphNode]) -> tuple[GraphNode, float] | None:
    """Return the candidate with the highest ``rapidfuzz.fuzz.WRatio`` against ``name``.

    WRatio combines several rapidfuzz scorers and is robust to substring,
    transposition, and token-reorder variants — a good general-purpose name
    matcher. Scores 0-100. Returns None when ``candidates`` is empty."""
    if not candidates:
        return None
    needle = normalize_name(name)
    best_score = -1.0
    best_node: GraphNode | None = None
    for node in candidates:
        score = float(fuzz.WRatio(needle, node.normalized_name))
        if score > best_score:
            best_score = score
            best_node = node
    if best_node is None:
        return None
    return best_node, best_score


def _new_node_id() -> str:
    """Stable, opaque node id. UUID4 is fine for the prototype — switch to a
    content-hash id if we ever need cross-system join keys (LightRAG §2.5)."""
    return f"e_{uuid.uuid4().hex[:16]}"


def _normalized_aliases(mention: ExtractedEntity, canonical_normalized: str) -> tuple[str, ...]:
    """Normalize + dedupe an entity's aliases, dropping the canonical form.

    Centralized so every code path that writes aliases applies the same
    normalization (and a future change is one edit, not five)."""
    out: set[str] = set()
    for raw in mention.aliases or ():
        norm = normalize_name(raw)
        if norm and norm != canonical_normalized:
            out.add(norm)
    return tuple(sorted(out))


def _now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


class GraphResolver:
    """Deterministic-first entity resolution against a :class:`GraphStore`.

    The store is mutated by ``link_or_create``: linking appends provenance to an
    existing node; creating writes a fresh node. The resolver does NOT mutate
    edges — the caller handles relation upserts after every mention has been
    resolved to a node id.
    """

    def __init__(
        self,
        store: GraphStore,
        *,
        disambiguator: LLMDisambiguator | None = None,
    ) -> None:
        self._store = store
        self._disambiguator = disambiguator

    async def link_or_create(
        self,
        mention: ExtractedEntity,
        *,
        chunk_id: str,
        document_id: str,
    ) -> ResolutionResult:
        """Resolve ``mention`` to a node id, creating a new node if no match.

        Provenance is appended to the chosen / created node so we always know
        which chunk asserted this entity (F5)."""
        raw_name = (mention.name or "").strip()
        if not raw_name:
            # Defensive: extractor should filter, but never write empty names.
            raise ValueError("GraphResolver.link_or_create: empty mention name")
        normalized = normalize_name(raw_name)
        mention_type = mention.type or "Entity"

        # --- Step 1: exact normalized-name match -------------------------------
        exact = self._store.find_by_name_exact(normalized, type=mention_type)
        if len(exact) == 1:
            self._link_provenance(
                exact[0], chunk_id, document_id,
                incoming_aliases=_normalized_aliases(mention, normalized),
            )
            return ResolutionResult(exact[0].id, branch="exact_link", llm_call=False)
        if len(exact) > 1:
            # Same name, different real-world entities — the two-Ahmeds case.
            picked = await self._llm_pick(mention, exact, chunk_id, document_id)
            if picked is not None:
                return picked
            # LLM said "none" → create new (the third Ahmed is a real possibility).

        # --- Step 2: entropy gate ---------------------------------------------
        # Untyped fallback search — a "Person" mention may also match generic
        # Entity rows (LLM downgraded the type earlier). We let fuzzy/LLM decide.
        candidates = self._store.find_candidates_by_name(
            raw_name, type=None, limit=FUZZY_CANDIDATE_LIMIT
        )
        # Always escalate short/common names to the LLM when there are candidates.
        if not _is_distinctive_name(normalized):
            if candidates:
                picked = await self._llm_pick(mention, candidates, chunk_id, document_id)
                if picked is not None:
                    return picked
            return self._create(mention, raw_name, normalized, chunk_id, document_id)

        # --- Step 3: fuzzy match (high-entropy names only) ---------------------
        if candidates:
            top = _best_fuzzy(raw_name, candidates)
            if top is not None and top[1] >= FUZZY_MATCH_THRESHOLD:
                node, _score = top
                self._link_provenance(
                    node, chunk_id, document_id,
                    incoming_aliases=_normalized_aliases(mention, normalized),
                )
                return ResolutionResult(node.id, branch="fuzzy_link", llm_call=False)
            # Below threshold but candidates exist → still worth asking the LLM
            # before creating a duplicate (cheap insurance for typo variants).
            picked = await self._llm_pick(mention, candidates, chunk_id, document_id)
            if picked is not None:
                return picked

        # --- Step 4: create new ------------------------------------------------
        return self._create(mention, raw_name, normalized, chunk_id, document_id)

    # ---- helpers ----

    async def _llm_pick(
        self,
        mention: ExtractedEntity,
        candidates: list[GraphNode],
        chunk_id: str,
        document_id: str,
    ) -> ResolutionResult | None:
        """Invoke the LLM disambiguator and apply its decision.

        Returns a ``ResolutionResult`` when the LLM picked a candidate, ``None``
        when the LLM said "no match" (so the caller creates a new node). When
        no disambiguator is configured, returns None — the deterministic ladder
        falls through to "create new" (safe default)."""
        if self._disambiguator is None or not candidates:
            return None
        try:
            picked_id = await self._disambiguator(mention, candidates)
        except Exception as exc:
            log.warning(
                "⚠️ graph.resolve — disambiguator failed · falling back to create-new",
                error=str(exc)[:200],
                exc_info=True,
            )
            return None
        if not picked_id:
            return None
        matched = next((c for c in candidates if c.id == picked_id), None)
        if matched is None:
            log.warning(
                "⚠️ graph.resolve — disambiguator returned unknown candidate id · ignoring",
                picked=picked_id,
            )
            return None
        self._link_provenance(
            matched, chunk_id, document_id,
            incoming_aliases=_normalized_aliases(mention, normalize_name(mention.name)),
        )
        return ResolutionResult(matched.id, branch="llm_link", llm_call=True)

    def _link_provenance(
        self,
        node: GraphNode,
        chunk_id: str,
        document_id: str,
        *,
        incoming_aliases: tuple[str, ...] = (),
    ) -> None:
        """Append the current source (chunk/doc) AND any newly-extracted aliases
        to an existing node — preserves all prior chunk_ids, document_ids, and
        aliases (F5 invariant + the alias accumulation path: bare 'mom' later
        finds Sara via the alias only because earlier mentions deposited it)."""
        merged_chunks = tuple([*node.chunk_ids, chunk_id]) if chunk_id else node.chunk_ids
        merged_docs = tuple([*node.document_ids, document_id]) if document_id else node.document_ids
        merged_aliases = tuple([*node.aliases, *incoming_aliases]) if incoming_aliases else node.aliases
        self._store.upsert_node(
            GraphNode(
                id=node.id,
                name=node.name,
                type=node.type,
                normalized_name=node.normalized_name,
                aliases=merged_aliases,  # adapter's upsert_node merges + dedupes
                chunk_ids=merged_chunks,
                document_ids=merged_docs,
                attrs=node.attrs,
                created_at=node.created_at,
            )
        )

    def _create(
        self,
        mention: ExtractedEntity,
        raw_name: str,
        normalized: str,
        chunk_id: str,
        document_id: str,
    ) -> ResolutionResult:
        # Aliases are stored NORMALIZED at write time so the exact-match Cypher
        # can do direct equality against the aliases[] column (no per-row
        # normalization on the read path). The canonical normalized_name is
        # excluded from aliases — find_by_name_exact already checks both.
        normalized_aliases = tuple(
            sorted({
                normalized_alias
                for raw_alias in (mention.aliases or [])
                if (normalized_alias := normalize_name(raw_alias))
                and normalized_alias != normalized
            })
        )
        node = GraphNode(
            id=_new_node_id(),
            name=raw_name,
            type=mention.type or "Entity",
            normalized_name=normalized,
            aliases=normalized_aliases,
            chunk_ids=(chunk_id,) if chunk_id else (),
            document_ids=(document_id,) if document_id else (),
            created_at=_now_iso(),
        )
        self._store.upsert_node(node)
        return ResolutionResult(node.id, branch="created", llm_call=False)


__all__ = ["GraphResolver", "LLMDisambiguator", "ResolutionResult"]
