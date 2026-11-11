import {
  GRAPH_RUNS_PAGE_SIZE,
  tailGraphRuns,
  type GraphLedgerRow,
  type GraphRunsTailResponse
} from '$lib/api/graph-runs';

export type GraphLedgerFileOffsets = Record<string, number>;

type LedgerPageResult =
  | { ok: true; rows: GraphLedgerRow[]; offsets: GraphLedgerFileOffsets; hasMore: boolean }
  | { ok: false; error: string };

/** Initial page: newest aggregate run rows, no time window. */
export async function graphRunsFetchInitialLedger(): Promise<LedgerPageResult> {
  // Step 1d: a failed request throws (answers are the data itself; there is no {ok, error} to test).
  let response: GraphRunsTailResponse;
  try {
    response = await tailGraphRuns({
      lines: GRAPH_RUNS_PAGE_SIZE,
      skip_from_end: 0
    });
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : 'Failed to load graph ledger.' };
  }
  return {
    ok: true,
    rows: response.rows,
    offsets: response.file_offsets,
    hasMore: response.has_more
  };
}

/** Older history page (counts from the newest end of the ledger). */
export async function graphRunsLoadMoreLedger(skipFromEnd: number): Promise<LedgerPageResult> {
  let response: GraphRunsTailResponse;
  try {
    response = await tailGraphRuns({
      lines: GRAPH_RUNS_PAGE_SIZE,
      skip_from_end: skipFromEnd
    });
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : 'Failed to load more graph runs.' };
  }
  return {
    ok: true,
    rows: response.rows,
    offsets: response.file_offsets,
    hasMore: response.has_more
  };
}

/** Delta poll using last known file offsets. */
export async function graphRunsPollLedgerTail(offsets: GraphLedgerFileOffsets): Promise<
  { ok: true; rows: GraphLedgerRow[]; offsets: GraphLedgerFileOffsets } | { ok: false }
> {
  let response: GraphRunsTailResponse;
  try {
    response = await tailGraphRuns({ after_offsets: offsets });
  } catch {
    return { ok: false };
  }
  return {
    ok: true,
    rows: response.rows,
    offsets: response.file_offsets
  };
}
