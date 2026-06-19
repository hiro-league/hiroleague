import type { RenderLogRow } from './logs-ui';

/** Mutable per-page-visit ordinal state (stable 1,2,3… per distinct ``scope_msg_id``). */
export type ScopeMsgOrdinalState = {
  ordinalMap: Map<string, number>;
  nextSeq: number;
};

export function createScopeMsgOrdinalState(): ScopeMsgOrdinalState {
  return { ordinalMap: new Map(), nextSeq: 1 };
}

export function resetScopeMsgOrdinalState(state: ScopeMsgOrdinalState): void {
  state.ordinalMap.clear();
  state.nextSeq = 1;
}

/** Assign next ordinal on first chronological sighting of each ``scope_msg_id`` in loaded rows. */
export function syncScopeMsgOrdinalsFromRows(
  state: ScopeMsgOrdinalState,
  allRows: RenderLogRow[]
): boolean {
  if (allRows.length === 0) return false;
  const sorted = [...allRows].sort((a, b) => a.timestamp - b.timestamp);
  let added = false;
  for (const row of sorted) {
    const id = row.scope_msg_id?.trim();
    if (!id) continue;
    if (!state.ordinalMap.has(id)) {
      state.ordinalMap.set(id, state.nextSeq++);
      added = true;
    }
  }
  return added;
}

export function getScopeMsgOrdinal(
  state: ScopeMsgOrdinalState,
  msgId: string | null | undefined
): number | null {
  const id = msgId?.trim();
  if (!id) return null;
  return state.ordinalMap.get(id) ?? null;
}

/**
 * Chip color A/B alternates when the message ordinal changes between consecutive visible rows
 * (rows without a scope column are skipped so the stripe does not flip on blank lines).
 */
export function computeScopeMsgChipStripeByRowKey(
  state: ScopeMsgOrdinalState,
  visibleRows: RenderLogRow[]
): Map<string, boolean> {
  const out = new Map<string, boolean>();
  let alt = false;
  let lastOrd: number | null = null;
  for (const row of visibleRows) {
    const id = row.scope_msg_id?.trim();
    if (!id) continue;
    const ord = state.ordinalMap.get(id) ?? null;
    if (ord == null) continue;
    if (lastOrd !== null && ord !== lastOrd) alt = !alt;
    lastOrd = ord;
    out.set(row._rowKey, alt);
  }
  return out;
}
