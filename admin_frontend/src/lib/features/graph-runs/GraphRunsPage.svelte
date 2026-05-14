<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { getGraphRun, tailGraphRuns, type GraphLedgerRow } from '$lib/api/graph-runs';

  let rows: GraphLedgerRow[] = $state([]);
  let selectedRunId = $state('');
  let timeline: GraphLedgerRow[] = $state([]);
  let langsmithUrl = $state<string | null>(null);
  let error = $state('');
  let offsets: Record<string, number> = {};
  let timer: ReturnType<typeof setInterval> | null = null;

  const filters = $state({
    chat_channel_id: '',
    character_id: '',
    model: '',
    decision_kind: ''
  });

  const visibleRows = $derived(
    [...rows].sort((a, b) => Number(b.ts || 0) - Number(a.ts || 0)).slice(0, 500)
  );

  async function loadInitial() {
    error = '';
    offsets = {};
    const response = await tailGraphRuns({
      lines: 500,
      since_seconds_ago: 86_400,
      filters: cleanFilters()
    });
    if (!response.ok || !response.data) {
      error = response.error ?? 'Failed to load graph ledger.';
      return;
    }
    rows = response.data.rows;
    offsets = response.data.file_offsets;
  }

  async function poll() {
    const response = await tailGraphRuns({
      after_offsets: offsets,
      filters: cleanFilters()
    });
    if (!response.ok || !response.data) return;
    offsets = response.data.file_offsets;
    if (response.data.rows.length > 0) {
      rows = [...rows, ...response.data.rows].slice(-1000);
    }
  }

  async function inspectRun(runId: string) {
    selectedRunId = runId;
    const response = await getGraphRun(runId);
    timeline = response.ok && response.data ? response.data.rows : [];
    langsmithUrl = response.ok && response.data ? (response.data.langsmith_url ?? null) : null;
  }

  function cleanFilters(): Record<string, string> {
    return Object.fromEntries(
      Object.entries(filters).filter(([, value]) => value.trim().length > 0)
    );
  }

  function formatTime(ts: number | '') {
    if (ts === '') return '';
    return new Date(ts * 1000).toLocaleTimeString();
  }

  function formatCost(value: number | '') {
    if (value === '') return '';
    return `$${value.toFixed(6)}`;
  }

  onMount(() => {
    loadInitial();
    timer = setInterval(poll, 2500);
  });

  onDestroy(() => {
    if (timer) clearInterval(timer);
  });
</script>

<svelte:head>
  <title>Graph Runs</title>
</svelte:head>

<section class="graph-runs-page">
  <header class="page-header">
    <div>
      <h1>Graph Runs</h1>
      <p>Per-node execution ledger for recent agent runs.</p>
    </div>
    <button type="button" onclick={loadInitial}>Refresh</button>
  </header>

  <div class="filters">
    <input bind:value={filters.chat_channel_id} placeholder="Channel id" oninput={loadInitial} />
    <input bind:value={filters.character_id} placeholder="Character" oninput={loadInitial} />
    <input bind:value={filters.model} placeholder="Model" oninput={loadInitial} />
    <input bind:value={filters.decision_kind} placeholder="Decision" oninput={loadInitial} />
  </div>

  {#if error}
    <p class="error">{error}</p>
  {/if}

  <div class="content-grid">
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Time</th>
            <th>Run</th>
            <th>Step</th>
            <th>Node</th>
            <th>Status</th>
            <th>ms</th>
            <th>Model</th>
            <th>Tokens</th>
            <th>Cost</th>
            <th>Decision</th>
          </tr>
        </thead>
        <tbody>
          {#each visibleRows as row (row.id)}
            <tr class:selected={row.run_id === selectedRunId}>
              <td>{formatTime(row.ts)}</td>
              <td><button type="button" class="link" onclick={() => inspectRun(row.run_id)}>{row.run_id}</button></td>
              <td>{row.step_index}</td>
              <td>{row.node}</td>
              <td>{row.status}</td>
              <td>{row.elapsed_ms}</td>
              <td>{row.model}</td>
              <td>{Number(row.input_tokens || 0) + Number(row.output_tokens || 0)}</td>
              <td>{formatCost(row.cost_usd)}</td>
              <td>{row.decision_kind}{row.decision_detail ? `:${row.decision_detail}` : ''}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>

    <aside>
      <div class="inspector-header">
        <h2>{selectedRunId || 'Run inspector'}</h2>
        {#if langsmithUrl}
          <a href={langsmithUrl} target="_blank" rel="noreferrer">Open in LangSmith</a>
        {/if}
      </div>
      <div class="timeline">
        {#each timeline as row (row.id)}
          <div class="timeline-row" class:substep={row.node.startsWith('tools/')}>
            <strong>{row.step_index}. {row.node}</strong>
            <span>{row.status} / {row.elapsed_ms}ms</span>
            <small>{row.decision_kind}{row.decision_detail ? `:${row.decision_detail}` : ''}</small>
          </div>
        {:else}
          <p>Select a run id to inspect its ordered timeline.</p>
        {/each}
      </div>
    </aside>
  </div>
</section>

<style>
  .graph-runs-page {
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 24px;
  }

  .page-header,
  .filters,
  .content-grid {
    display: flex;
    gap: 12px;
  }

  .page-header {
    align-items: center;
    justify-content: space-between;
  }

  h1,
  h2,
  p {
    margin: 0;
  }

  h1 {
    font-size: 24px;
  }

  h2 {
    font-size: 16px;
  }

  p {
    color: var(--muted-foreground, #64748b);
    font-size: 13px;
  }

  button,
  input {
    border: 1px solid var(--border, #d4d4d8);
    border-radius: 6px;
    background: var(--background, #fff);
    color: inherit;
    font: inherit;
  }

  button {
    cursor: pointer;
    padding: 8px 12px;
  }

  input {
    min-width: 0;
    padding: 8px 10px;
  }

  .filters {
    flex-wrap: wrap;
  }

  .content-grid {
    align-items: stretch;
    min-height: 0;
  }

  .table-wrap {
    flex: 1 1 auto;
    overflow: auto;
    border: 1px solid var(--border, #d4d4d8);
    border-radius: 8px;
  }

  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 12px;
    white-space: nowrap;
  }

  th,
  td {
    border-bottom: 1px solid var(--border, #e4e4e7);
    padding: 8px 10px;
    text-align: left;
  }

  th {
    position: sticky;
    top: 0;
    background: var(--background, #fff);
    z-index: 1;
  }

  tr.selected {
    background: color-mix(in srgb, var(--accent, #0ea5e9) 10%, transparent);
  }

  .link {
    border: 0;
    background: transparent;
    color: var(--primary, #0369a1);
    padding: 0;
  }

  aside {
    flex: 0 0 320px;
    border: 1px solid var(--border, #d4d4d8);
    border-radius: 8px;
    padding: 12px;
  }

  .timeline {
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin-top: 12px;
  }

  .inspector-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }

  .inspector-header a {
    border: 1px solid var(--border, #d4d4d8);
    border-radius: 6px;
    color: var(--primary, #0369a1);
    font-size: 12px;
    padding: 6px 8px;
    text-decoration: none;
    white-space: nowrap;
  }

  .timeline-row {
    display: grid;
    gap: 4px;
    border-bottom: 1px solid var(--border, #e4e4e7);
    padding-bottom: 8px;
    font-size: 12px;
  }

  .timeline-row.substep {
    border-left: 2px solid var(--primary, #0369a1);
    padding-left: 10px;
  }

  .timeline-row span,
  .timeline-row small,
  .error {
    color: var(--muted-foreground, #64748b);
  }
</style>
