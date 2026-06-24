/** Frontend display labels for schema enum domains (presentation copy stays client-side). */

export const GRAPH_BACKEND_LABELS = {
  off: 'Off — flat Qdrant only',
  graphiti: 'Graphiti — graph facts (recommended)'
} as const;

export const GRAPH_TEMPORAL_DEFAULT_LABELS = {
  current: 'Current facts only',
  all: 'Include historical'
} as const;

export const GRAPH_SEARCH_RECIPE_LABELS = {
  rrf: 'RRF',
  mmr: 'MMR',
  cross_encoder: 'Cross-encoder'
} as const;

export const GRAPH_SEARCH_SCOPE_LABELS = {
  edges: 'Edges (facts only)',
  edges_and_nodes: 'Edges + Nodes',
  edges_and_episodes: 'Edges + Episodes',
  edges_nodes_episodes: 'Edges + Nodes + Episodes'
} as const;

export const GRAPH_OBSERVABILITY_LABELS = {
  off: 'Off (no graph ledger)',
  ledger: 'Ledger (cost + roll-up · default)',
  trace: 'Trace (+ deep per-stage sidecars)'
} as const;

export const KNOWLEDGE_LANGUAGE_POLICY_LABELS = {
  match_query: 'Match query',
  prefer_english: 'Prefer English',
  prefer_arabic: 'Prefer Arabic'
} as const;
