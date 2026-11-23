// The one list's rules: the order of its rows, the kind filter, what the Status column says, and which rows have
// a Settings panel. Pure, so the page and its tests share them.
import type { ExtensionRow } from '$lib/api/extensions';

export type ExtensionKind = ExtensionRow['kind'];

/** Channels first (the family's chat), then apps; each by its label. */
export function sortExtensions(rows: ExtensionRow[]): ExtensionRow[] {
  return [...rows].sort((a, b) =>
    a.kind === b.kind ? a.label.localeCompare(b.label) : a.kind === 'channel' ? -1 : 1
  );
}

/** The rows of the kinds picked; none picked keeps every row. */
export function ofKinds(rows: ExtensionRow[], kinds: ExtensionKind[]): ExtensionRow[] {
  return kinds.length ? rows.filter((row) => kinds.includes(row.kind)) : rows;
}

export function countKinds(rows: ExtensionRow[]): Record<ExtensionKind, number> {
  return {
    channel: rows.filter((row) => row.kind === 'channel').length,
    app: rows.filter((row) => row.kind === 'app').length
  };
}

export type StatusLine = { tone: 'ok' | 'off' | 'warn'; text: string };

/** What the Status column says: off, not connected, connected but its account not linked, or connected. */
export function statusOf(row: ExtensionRow): StatusLine {
  if (row.enabled === false) return { tone: 'off', text: 'Off' };
  if (!row.connected) return { tone: 'warn', text: 'Not connected' };
  if (row.linked === false) return { tone: 'warn', text: 'Connected, not linked' };
  return { tone: 'ok', text: 'Connected' };
}

/** The time under the status: since it connected, or when it was last seen. */
export function statusTime(row: ExtensionRow): { words: string; at: string } | null {
  if (row.connected && row.connected_at) return { words: 'since', at: row.connected_at };
  if (row.last_seen) return { words: 'last seen', at: row.last_seen };
  return null;
}

/** A row has a Settings panel when the core keeps its settings or it links an account; an app keeps its own. */
export function hasSettings(row: ExtensionRow): boolean {
  return row.started_by_core && (row.has_settings || row.pairing !== '');
}
