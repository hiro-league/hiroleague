import { GRAPH_RUNS_PAGE_SIZE, tailGraphRuns, type GraphLedgerRow } from '$lib/api/graph-runs';

export type GraphLedgerFileOffsets = Record<string, number>;

type LedgerPageResult =
  | { ok: true; rows: GraphLedgerRow[]; offsets: GraphLedgerFileOffsets; hasMore: boolean }
  | { ok: false; error: string };

/** Initial page: newest aggregate run rows, no time window. */
export async function graphRunsFetchInitialLedger(): Promise<LedgerPageResult> {
  const response = await tailGraphRuns({
    lines: GRAPH_RUNS_PAGE_SIZE,
    skip_from_end: 0
  });
  if (!response.ok || !response.data) {
    return { ok: false, error: response.error ?? 'Failed to load graph ledger.' };
  }
  return {
    ok: true,
    rows: response.data.rows,
    offsets: response.data.file_offsets,
    hasMore: response.data.has_more
  };
}

/** Older history page (counts from the newest end of the ledger). */
export async function graphRunsLoadMoreLedger(skipFromEnd: number): Promise<LedgerPageResult> {
  const response = await tailGraphRuns({
    lines: GRAPH_RUNS_PAGE_SIZE,
    skip_from_end: skipFromEnd
  });
  if (!response.ok || !response.data) {
    return { ok: false, error: response.error ?? 'Failed to load more graph runs.' };
  }
  return {
    ok: true,
    rows: response.data.rows,
    offsets: response.data.file_offsets,
    hasMore: response.data.has_more
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
