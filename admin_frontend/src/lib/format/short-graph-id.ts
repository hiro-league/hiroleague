/** Truncate a node/edge uuid for compact display when a human-readable name is missing. */
export function shortGraphId(id: string): string {
  const s = String(id ?? '').trim();
  return s.length > 8 ? `${s.slice(0, 8)}…` : s;
}
