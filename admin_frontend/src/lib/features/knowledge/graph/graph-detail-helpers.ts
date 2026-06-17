/**
 * Pure helpers for the graph detail panel (no Svelte/DOM). Kept side-effect-free so they
 * unit-test trivially and keep the .svelte file thin (svelte-best-practice §2).
 */
import type { GraphEdgeDTO } from '$lib/api/knowledge';

/** One run of text, flagged as a search match or not — rendered with <mark> when match. */
export type TextPart = { text: string; match: boolean };

/** Split `text` into matched/unmatched runs for case-insensitive `query` highlighting.
 *  Empty/blank query → the whole string as one non-match run (so callers render plainly).
 *  Avoids `{@html}`: the component renders each part as a real text node. */
export function highlightParts(text: string, query: string): TextPart[] {
  const q = query.trim();
  if (!q || !text) return [{ text, match: false }];
  const hay = text.toLowerCase();
  const needle = q.toLowerCase();
  const parts: TextPart[] = [];
  let i = 0;
  while (i < text.length) {
    const idx = hay.indexOf(needle, i);
    if (idx === -1) {
      parts.push({ text: text.slice(i), match: false });
      break;
    }
    if (idx > i) parts.push({ text: text.slice(i, idx), match: false });
    parts.push({ text: text.slice(idx, idx + needle.length), match: true });
    i = idx + needle.length;
  }
  return parts;
}

/** Case-insensitive substring test (blank query never matches). */
export function hasMatch(text: string, query: string): boolean {
  const q = query.trim().toLowerCase();
  return q ? text.toLowerCase().includes(q) : false;
}

/** One row in the Connections tab when an ENTITY is selected: the edge + its other endpoint. */
export type NodeConnection = {
  edgeId: string;
  relType: string;
  fact: string;
  neighborId: string;
  outgoing: boolean; // true: node → neighbor (node is the source); false: neighbor → node
  invalid: boolean; // superseded/retired fact (invalid_at or expired_at set)
};

const edgeInvalid = (e: GraphEdgeDTO): boolean => e.invalid_at != null || e.expired_at != null;

/** Every edge touching `nodeId`, as Connections rows (the neighbor is the other endpoint).
 *  Self-loops (source === target) list the node itself as the neighbor. Ordered: current facts
 *  before superseded, then by relation name, for a stable, readable list. */
export function connectionsForNode(nodeId: string, edges: GraphEdgeDTO[]): NodeConnection[] {
  const rows: NodeConnection[] = [];
  for (const e of edges) {
    const isSource = e.source === nodeId;
    const isTarget = e.target === nodeId;
    if (!isSource && !isTarget) continue;
    rows.push({
      edgeId: e.id,
      relType: e.rel_type,
      fact: e.fact,
      neighborId: isSource ? e.target : e.source,
      outgoing: isSource,
      invalid: edgeInvalid(e)
    });
  }
  rows.sort(
    (a, b) =>
      Number(a.invalid) - Number(b.invalid) || a.relType.localeCompare(b.relType)
  );
  return rows;
}

/** Resolve an aggregate edge's `collapsedIds` to the real edges it folds (skips any missing). */
export function collapsedEdges(
  collapsedIds: string[],
  edgeById: Map<string, GraphEdgeDTO>
): GraphEdgeDTO[] {
  const out: GraphEdgeDTO[] = [];
  for (const id of collapsedIds) {
    const e = edgeById.get(id);
    if (e) out.push(e);
  }
  out.sort((a, b) => Number(edgeInvalid(a)) - Number(edgeInvalid(b)) || a.rel_type.localeCompare(b.rel_type));
  return out;
}
