import { tailGraphRuns, type GraphLedgerRow } from '$lib/api/graph-runs';

export type GraphLedgerFileOffsets = Record<string, number>;

/** Initial tail window for the ledger list on graph-runs browse. */
export async function graphRunsFetchInitialLedger(): Promise<
  { ok: true; rows: GraphLedgerRow[]; offsets: GraphLedgerFileOffsets } | { ok: false; error: string }
> {
  const response = await tailGraphRuns({
    lines: 500,
    since_seconds_ago: 86_400
  });
  if (!response.ok || !response.data) {
    return { ok: false, error: response.error ?? 'Failed to load graph ledger.' };
  }
  return {
    ok: true,
    rows: response.data.rows,
    offsets: response.data.file_offsets
  };
}

/** Delta poll using last known file offsets. */
export async function graphRunsPollLedgerTail(offsets: GraphLedgerFileOffsets): Promise<
  { ok: true; rows: GraphLedgerRow[]; offsets: GraphLedgerFileOffsets } | { ok: false }
> {
  const response = await tailGraphRuns({ after_offsets: offsets });
  if (!response.ok || !response.data) {
    return { ok: false };
  }
  return {
    ok: true,
    rows: response.data.rows,
    offsets: response.data.file_offsets
  };
}
