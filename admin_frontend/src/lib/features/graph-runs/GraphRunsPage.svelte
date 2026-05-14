<script lang="ts">
  import { onMount } from 'svelte';
  import { listChatChannels, type ChatChannelRow } from '$lib/api/chat-channels';
  import { getCharacter, type CharacterDetail } from '$lib/api/characters';
  import {
    getGraphRun,
    GRAPH_RUN_HEADER_TAB_FIELDS,
    GRAPH_RUN_NODE_TABLE_FIELDS,
    tailGraphRuns,
    type GraphLedgerRow
  } from '$lib/api/graph-runs';
  import {
    formatAgentElapsedMs,
    formatTokenInteger,
    formatUsdCostDisplay
  } from '$lib/features/chat-channels/messages/agent-message-meta';

  /**
   * Normalizes aggregate `status` for the toolbar dot (toolbar carries previews; grid omits status).
   * Add new branches here if the ledger introduces more terminal status slugs.
   */
  function runStatusDataValue(status: string): string {
    const s = String(status || '').trim().toLowerCase();
    if (s === 'completed') return 'completed';
    if (s === 'failed') return 'failed';
    if (s === 'cancelled' || s === 'canceled') return 'cancelled';
    if (s === 'skipped') return 'skipped';
    if (!s) return 'unknown';
    return 'other';
  }

  const RUNS_TAB = 'runs' as const;
  type ActivePane = typeof RUNS_TAB | string;

  let rows: GraphLedgerRow[] = $state([]);
  let openRunIds: string[] = $state([]);
  let activePane: ActivePane = $state(RUNS_TAB);

  let timelineByRun = $state<Record<string, GraphLedgerRow[]>>({});
  let langsmithUrlByRun = $state<Record<string, string | undefined>>({});
  let aggregateByRun = $state<Record<string, GraphLedgerRow | null>>({});
  let chatChannels = $state<ChatChannelRow[]>([]);
  let titleCharacter = $state<CharacterDetail | null>(null);

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

  const timeline = $derived(
    activePane === RUNS_TAB ? [] : (timelineByRun[activePane] ?? [])
  );

  /** Prefer inspect payload; fallback to tails stream aggregate row until next open. */

  const activeRunAggregate = $derived.by(() => {
    if (activePane === RUNS_TAB) return null;
    const rid = activePane;
    const fromInspect = aggregateByRun[rid];
    if (fromInspect) return fromInspect;
    return rows.find((row) => row.run_id === rid && String(row.row_kind) === 'run') ?? null;
  });

  const langsmithUrlForActive = $derived(
    activePane === RUNS_TAB ? null : (langsmithUrlByRun[activePane] ?? null)
  );

  /** Prefer aggregate (incl. tail fallback via ``activeRunAggregate``); else first node row. */
  const runIdentitySource = $derived.by((): GraphLedgerRow | null => {
    if (activePane === RUNS_TAB) return null;
    const agg = activeRunAggregate;
    if (agg) return agg;
    const tl = timelineByRun[activePane] ?? [];
    return tl[0] ?? null;
  });

  const activeChannelLabel = $derived.by(() => {
    const row = runIdentitySource;
    if (!row) return '';
    const id = row.chat_channel_id;
    if (id === '' || typeof id !== 'number') return '';
    const ch = chatChannels.find((c) => c.id === id);
    return ch?.name?.trim() ?? '';
  });

  const runTitlePrimary = $derived.by(() => {
    const row = runIdentitySource;
    const name = titleCharacter?.name?.trim();
    if (name) return name;
    const cid = String(row?.character_id ?? '').trim();
    return cid || '—';
  });

  const runTitleSubtitle = $derived.by(() => {
    const parts: string[] = [];
    const ch = activeChannelLabel;
    if (ch) parts.push(ch);
    else if (runIdentitySource?.chat_channel_id !== '' && runIdentitySource?.chat_channel_id != null) {
      parts.push(`Channel ${runIdentitySource.chat_channel_id}`);
    }
    return parts.join(' · ');
  });

  const toolbarTotalCostLabel = $derived.by(() => {
    const agg = activeRunAggregate;
    if (!agg) return '';
    const raw = agg.cost_usd;
    const n = typeof raw === 'number' ? raw : Number(raw);
    if (!Number.isFinite(n)) return '';
    return formatUsdCostDisplay(n) || (n === 0 ? '$0.00' : '');
  });

  const toolbarElapsedLabel = $derived.by(() => {
    const agg = activeRunAggregate;
    if (!agg) return '';
    const raw = agg.elapsed_ms;
    if (raw === '') return '';
    const n = typeof raw === 'number' ? raw : Number(raw);
    if (!Number.isFinite(n)) return '';
    return formatAgentElapsedMs(n);
  });

  const headerFieldList = GRAPH_RUN_HEADER_TAB_FIELDS;
  const nodeFieldList = GRAPH_RUN_NODE_TABLE_FIELDS;

  /** Short column titles for ledger keys (dense tables). */

  function fieldLabel(field: keyof GraphLedgerRow): string {
    const map: Partial<Record<keyof GraphLedgerRow, string>> = {
      ts: 'Time',
      run_id: 'Run',
      step_index: 'Step',
      node: 'Node',
      node_attempt: 'Attempt',
      branch_index: 'Branch',
      status: 'Status',
      elapsed_ms: 'ms',
      inbound_id: 'Inbound',
      chat_channel_id: 'Channel',
      device_id: 'Device',
      user_id: 'User',
      character_id: 'Character',
      provider: 'Provider',
      model: 'Model',
      input_tokens: 'In tok',
      output_tokens: 'Out tok',
      cached_input_tokens: 'Cached in',
      reasoning_tokens: 'Reason tok',
      tts_chars: 'TTS characters',
      stt_audio_seconds: 'STT user audio (s)',
      tts_audio_seconds: 'TTS audio out (s)',
      cost_usd: 'Cost',
      pricing_version: 'Pricing',
      decision_kind: 'Decision',
      decision_detail: 'Detail',
      error_code: 'Error',
      row_kind: 'Row kind',
      input_preview: 'Input preview',
      output_preview: 'Output preview',
      id: 'Row id'
    };
    return map[field] ?? String(field).replace(/_/g, ' ');
  }

  function formatLedgerField(field: keyof GraphLedgerRow, row: GraphLedgerRow): string {
    const raw = row[field];
    if (raw === '' || raw === null || raw === undefined) return '—';
    if (field === 'ts') {
      const n = typeof raw === 'number' ? raw : Number(raw);
      return Number.isFinite(n) ? formatTime(n) : String(raw);
    }
    if (field === 'cost_usd') {
      const n = typeof raw === 'number' ? raw : Number(raw);
      return Number.isFinite(n) ? formatCost(n) : String(raw);
    }
    if (field === 'stt_audio_seconds' || field === 'tts_audio_seconds') {
      const n = typeof raw === 'number' ? raw : Number(raw);
      return Number.isFinite(n) ? n.toFixed(3) : String(raw);
    }
    return String(raw);
  }

  async function loadChatChannels() {
    const response = await listChatChannels();
    if (response.ok && response.data) {
      chatChannels = response.data;
    }
  }

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

  async function loadRunDetail(runId: string) {
    const response = await getGraphRun(runId);
    if (response.ok && response.data) {
      timelineByRun[runId] = response.data.rows;
      aggregateByRun[runId] = response.data.aggregate ?? null;
      langsmithUrlByRun[runId] = response.data.langsmith_url ?? undefined;
      timelineByRun = { ...timelineByRun };
      aggregateByRun = { ...aggregateByRun };
      langsmithUrlByRun = { ...langsmithUrlByRun };
    } else if (!response.ok) {
      timelineByRun[runId] = [];
      aggregateByRun[runId] = null;
      timelineByRun = { ...timelineByRun };
      aggregateByRun = { ...aggregateByRun };
      langsmithUrlByRun[runId] = undefined;
      langsmithUrlByRun = { ...langsmithUrlByRun };
    }
  }

  async function openRunTab(runId: string) {
    if (!openRunIds.includes(runId)) {
      openRunIds = [...openRunIds, runId];
    }
    activePane = runId;
    await loadRunDetail(runId);
  }

  function closeRunTab(runId: string) {
    openRunIds = openRunIds.filter((id) => id !== runId);
    delete timelineByRun[runId];
    delete aggregateByRun[runId];
    delete langsmithUrlByRun[runId];
    timelineByRun = { ...timelineByRun };
    aggregateByRun = { ...aggregateByRun };
    langsmithUrlByRun = { ...langsmithUrlByRun };
    activePane = RUNS_TAB;
  }

  function showRunsOnly() {
    activePane = RUNS_TAB;
  }

  function tabLabel(runId: string) {
    if (runId.length <= 18) return runId;
    return `${runId.slice(0, 10)}…${runId.slice(-6)}`;
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
    if (value === '') return '—';
    const label = formatUsdCostDisplay(value);
    return label || '—';
  }

  /** Duration / fractional seconds — ledger STT/TTS audio fields. */
  function formatSecondsCardValue(raw: number | ''): string {
    if (raw === '' || raw === null || raw === undefined) return '—';
    const n = typeof raw === 'number' ? raw : Number(raw);
    if (!Number.isFinite(n)) return '—';
    return `${n.toFixed(3)} s`;
  }

  /** Token totals on aggregate row — dashboard cards use integer grouping like chat telemetry. */
  function formatTokenCardValue(raw: number | ''): string {
    if (raw === '' || raw === null || raw === undefined) return '—';
    const n = typeof raw === 'number' ? raw : Number(raw);
    if (!Number.isFinite(n)) return '—';
    return formatTokenInteger(n);
  }

  function onEscapeKey(ev: KeyboardEvent) {
    if (ev.key !== 'Escape') return;
    if (activePane === RUNS_TAB) return;
    const focus = ev.target instanceof HTMLElement ? ev.target : null;
    if (focus?.closest('input, textarea, select, [contenteditable="true"]')) return;
    ev.preventDefault();
    closeRunTab(activePane);
  }

  $effect(() => {
    if (activePane === RUNS_TAB) {
      titleCharacter = null;
      return;
    }
    const cid = String(runIdentitySource?.character_id ?? '').trim();
    if (!cid) {
      titleCharacter = null;
      return;
    }
    titleCharacter = null;
    let cancelled = false;
    void getCharacter(cid).then((res) => {
      if (cancelled) return;
      titleCharacter = res.ok && res.data ? res.data : null;
    });
    return () => {
      cancelled = true;
    };
  });

  onMount(() => {
    loadInitial();
    void loadChatChannels();
    timer = setInterval(poll, 2500);
    window.addEventListener('keydown', onEscapeKey);
    return () => {
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
      window.removeEventListener('keydown', onEscapeKey);
    };
  });
</script>

<!--
  Single-run tab: toolbar, token/model metric cards, aggregate dl, node table.
-->
<svelte:head>
  <title>Graph Runs</title>
</svelte:head>

<section class="graph-runs-page">
  <header class="page-header">
    <div>
      <h1>Graph Runs</h1>
      <p>Recent agent turns with aggregate cost, latency, and drill-down timelines.</p>
    </div>
    <button type="button" onclick={loadInitial}>Refresh</button>
  </header>

  <nav class="tab-bar" aria-label="Graph runs views">
    <button
      type="button"
      class="tab tab-runs"
      class:active={activePane === RUNS_TAB}
      onclick={showRunsOnly}
    >
      Graph runs
    </button>
    {#each openRunIds as rid (rid)}
      <div class="tab tab-run" class:active={activePane === rid}>
        <button type="button" class="tab-main" onclick={() => openRunTab(rid)}>
          {tabLabel(rid)}
        </button>
        <button
          type="button"
          class="tab-close"
          aria-label="Close run details"
          title="Close (Esc)"
          onclick={(e) => {
            e.stopPropagation();
            closeRunTab(rid);
          }}
        >
          ✕
        </button>
      </div>
    {/each}
  </nav>

  {#if activePane === RUNS_TAB}
    <div class="filters">
      <input bind:value={filters.chat_channel_id} placeholder="Channel id" oninput={loadInitial} />
      <input bind:value={filters.character_id} placeholder="Character" oninput={loadInitial} />
      <input bind:value={filters.model} placeholder="Model" oninput={loadInitial} />
      <input bind:value={filters.decision_kind} placeholder="Decision" oninput={loadInitial} />
    </div>
  {/if}

  {#if error}
    <p class="error">{error}</p>
  {/if}

  {#if activePane === RUNS_TAB}
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Time</th>
            <th>Run</th>
            <th>Status</th>
            <th>Model</th>
            <th>Tokens</th>
            <th>Cost</th>
            <th>Decision</th>
            <th>Input</th>
            <th>Output</th>
          </tr>
        </thead>
        <tbody>
          {#each visibleRows as row (row.id)}
            <tr class:muted-open={openRunIds.includes(row.run_id)}>
              <td>{formatTime(row.ts)}</td>
              <td>
                <button type="button" class="link" onclick={() => openRunTab(row.run_id)}>{row.run_id}</button>
              </td>
              <td>{row.status}</td>
              <td>{row.model}</td>
              <td>{Number(row.input_tokens || 0) + Number(row.output_tokens || 0)}</td>
              <td>{formatCost(row.cost_usd)}</td>
              <td>{row.decision_kind}{row.decision_detail ? `:${row.decision_detail}` : ''}</td>
              <td class="preview">{row.input_preview}</td>
              <td class="preview">{row.output_preview}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {:else}
    <div class="run-detail">
      <div class="run-detail-header-row">
        <div class="run-detail-toolbar">
          <div class="run-toolbar-lead">
            <span
              class="run-status-dot"
              data-status={runStatusDataValue(activeRunAggregate?.status ?? '')}
              title={activeRunAggregate?.status ? `Status: ${activeRunAggregate.status}` : 'No aggregate row yet'}
              aria-label={activeRunAggregate?.status ? `Run status: ${activeRunAggregate.status}` : 'Run status unknown'}
            ></span>
            {#if titleCharacter?.photo_data_url}
              <img
                class="run-title-avatar"
                src={titleCharacter.photo_data_url}
                alt=""
                width="40"
                height="40"
              />
            {:else}
              <div class="run-title-avatar run-title-avatar--placeholder" aria-hidden="true"></div>
            {/if}
            <div class="run-title-block">
              <div class="run-title-top">
                <h2 class="run-detail-title">{runTitlePrimary}</h2>
                {#if langsmithUrlForActive}
                  <a
                    class="title-langsmith-link"
                    href={langsmithUrlForActive}
                    target="_blank"
                    rel="noreferrer"
                    title="LangSmith graph trace"
                    >LangSmith</a
                  >
                {/if}
              </div>
              {#if runTitleSubtitle}
                <p class="run-title-sub">Channel: {runTitleSubtitle}</p>
              {/if}
              <p class="run-title-runid mono" title={activePane}>{activePane}</p>
            </div>
          </div>
        </div>
        {#if activeRunAggregate}
          <div class="run-preview-cards" aria-label="Input and output previews">
            <div class="run-metric-card run-metric-card--preview">
              <span class="run-metric-card-label">Input preview</span>
              <p class="run-preview-card-text">{activeRunAggregate.input_preview || '—'}</p>
            </div>
            <div class="run-metric-card run-metric-card--preview">
              <span class="run-metric-card-label">Output preview</span>
              <p class="run-preview-card-text">{activeRunAggregate.output_preview || '—'}</p>
            </div>
          </div>
          <div
            class="run-metric-card run-metric-card--elapsed-total"
            aria-label="Elapsed time and total cost"
          >
            <div class="run-elapsed-total-inner">
              <div class="run-toolbar-elapsed" aria-label="Run duration">
                <span class="run-toolbar-metric-label">Elapsed Time</span>
                <span class="run-toolbar-elapsed-value">{toolbarElapsedLabel || '—'}</span>
              </div>
              <div class="run-toolbar-cost" aria-label="Total run cost">
                <span class="run-toolbar-metric-label">Total Cost</span>
                <span class="run-toolbar-cost-value">{toolbarTotalCostLabel || '—'}</span>
              </div>
            </div>
          </div>
        {/if}
      </div>

      {#if activeRunAggregate}
        <div class="run-aggregate-dashboard" aria-label="Run usage and model">
          <div class="run-metric-cards">
            <div class="run-metric-card run-metric-card--tokens">
              <div class="run-token-grid">
                <div class="run-token-stat">
                  <span class="run-token-stat-label">In</span>
                  <span class="run-token-stat-value">{formatTokenCardValue(activeRunAggregate.input_tokens)}</span>
                </div>
                <div class="run-token-stat">
                  <span class="run-token-stat-label">Cached</span>
                  <span class="run-token-stat-value"
                    >{formatTokenCardValue(activeRunAggregate.cached_input_tokens)}</span
                  >
                </div>
                <div class="run-token-stat">
                  <span class="run-token-stat-label">Out</span>
                  <span class="run-token-stat-value">{formatTokenCardValue(activeRunAggregate.output_tokens)}</span>
                </div>
                <div class="run-token-stat">
                  <span class="run-token-stat-label">Reasoning</span>
                  <span class="run-token-stat-value"
                    >{formatTokenCardValue(activeRunAggregate.reasoning_tokens)}</span
                  >
                </div>
              </div>
            </div>
            <div class="run-metric-card run-metric-card--model">
              <span class="run-metric-card-label">Provider / model</span>
              <div class="run-metric-card-model">
                <span class="mono run-metric-card-model-line"
                  >{String(activeRunAggregate.provider || '').trim() || '—'}</span
                >
                <span class="mono run-metric-card-model-line run-metric-card-model-id"
                  >{String(activeRunAggregate.model || '').trim() || '—'}</span
                >
              </div>
            </div>
            <div class="run-metric-card run-metric-card--speech">
              <div class="run-speech-grid" role="group" aria-label="Speech-to-text and text-to-speech usage">
                <div class="run-token-stat">
                  <div class="run-metric-stat-heading">
                    <abbr class="run-metric-stat-kicker" title="Speech-to-text (STT)">STT</abbr>
                    <span class="run-metric-stat-desc">User audio received · transcribed</span>
                  </div>
                  <span class="run-token-stat-value"
                    >{formatSecondsCardValue(activeRunAggregate.stt_audio_seconds)}</span
                  >
                </div>
                <div class="run-token-stat">
                  <div class="run-metric-stat-heading">
                    <abbr class="run-metric-stat-kicker" title="Text-to-speech (TTS)">TTS</abbr>
                    <span class="run-metric-stat-desc">Characters synthesized into speech</span>
                  </div>
                  <span class="run-token-stat-value">{formatTokenCardValue(activeRunAggregate.tts_chars)}</span>
                </div>
                <div class="run-token-stat">
                  <div class="run-metric-stat-heading">
                    <abbr class="run-metric-stat-kicker" title="Text-to-speech (TTS) audio">TTS</abbr>
                    <span class="run-metric-stat-desc">Duration of generated speech audio</span>
                  </div>
                  <span class="run-token-stat-value"
                    >{formatSecondsCardValue(activeRunAggregate.tts_audio_seconds)}</span
                  >
                </div>
              </div>
            </div>
          </div>
        </div>
        <dl class="run-header-grid">
          {#each headerFieldList as field (field)}
            <dt title={field}>{fieldLabel(field)}</dt>
            <dd class="mono">{formatLedgerField(field, activeRunAggregate)}</dd>
          {/each}
        </dl>
      {:else}
        <p class="warn">
          No aggregate (<code class="mono">row_kind=run</code>) line found for this run in the ledger yet.
          Node timeline below still loads when present.
        </p>
      {/if}

      <p class="section-label">Nodes</p>
      <div class="table-wrap nodes-scroll">
        <table class="nodes-table">
          <thead>
            <tr>
              {#each nodeFieldList as field (field)}
                <th title={field}>{fieldLabel(field)}</th>
              {/each}
            </tr>
          </thead>
          <tbody>
            {#each timeline as row (row.id)}
              <tr class:substep={row.node.startsWith('tools/')}>
                {#each nodeFieldList as field (field)}
                  <td class="mono">{formatLedgerField(field, row)}</td>
                {/each}
              </tr>
            {:else}
              <tr class="placeholder-row">
                <td colspan={nodeFieldList.length}>No node rows loaded.</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </div>
  {/if}
</section>

<style>
  .graph-runs-page {
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 24px;
  }

  .page-header,
  .filters {
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

  .section-label {
    margin-top: 8px;
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--muted-foreground, #64748b);
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

  .tab-bar {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: 4px;
    border-bottom: 1px solid var(--border, #d4d4d8);
    padding-bottom: 0;
  }

  .tab {
    display: inline-flex;
    align-items: center;
    border: 1px solid transparent;
    border-bottom: none;
    border-radius: 8px 8px 0 0;
    background: transparent;
    font-size: 13px;
  }

  .tab-runs.tab {
    padding: 8px 14px;
  }

  .tab-run {
    max-width: 220px;
  }

  .tab.active {
    border-color: var(--border, #d4d4d8);
    background: var(--background, #fff);
    margin-bottom: -1px;
    padding-bottom: 1px;
  }

  .tab-main {
    border: none;
    background: transparent;
    flex: 1 1 auto;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    text-align: left;
    padding: 8px 4px 8px 10px;
  }

  .tab-close {
    border: none;
    background: transparent;
    color: var(--muted-foreground, #64748b);
    padding: 8px 10px;
    line-height: 1;
    font-size: 14px;
    flex-shrink: 0;
  }

  .tab-close:hover {
    color: var(--foreground, #0f172a);
  }

  .table-wrap {
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

  .preview {
    max-width: 220px;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  th {
    position: sticky;
    top: 0;
    background: var(--background, #fff);
    z-index: 1;
  }

  .nodes-scroll {
    max-height: min(70vh, 720px);
  }

  .nodes-table tbody tr.substep {
    background: color-mix(in srgb, var(--primary, #0ea5e9) 8%, transparent);
  }

  tr.muted-open {
    background: color-mix(in srgb, var(--accent, #0ea5e9) 8%, transparent);
  }

  .link {
    border: 0;
    background: transparent;
    color: var(--primary, #0369a1);
    padding: 0;
  }

  .run-detail {
    display: flex;
    flex-direction: column;
    gap: 14px;
  }

  /* Header strip: identity card · capped preview cards · time/cost · equal row height via align-items stretch. */

  .run-detail-header-row {
    display: flex;
    flex-wrap: wrap;
    align-items: stretch;
    gap: 12px;
    min-width: 0;
  }

  .run-detail-toolbar {
    display: flex;
    flex-wrap: wrap;
    align-items: stretch;
    gap: 12px 16px;
    padding: 10px 12px;
    border: 1px solid var(--border, #d4d4d8);
    border-radius: 8px;
    background: color-mix(in srgb, var(--muted-foreground, #64748b) 5%, transparent);
    flex: 1 1 minmax(280px, 1fr);
    min-width: 0;
    align-self: stretch;
    box-sizing: border-box;
  }

  @media (max-width: 900px) {
    .run-detail-header-row {
      flex-direction: column;
    }

    .run-detail-toolbar {
      flex: 1 1 auto;
      width: 100%;
    }

    .run-metric-card--elapsed-total {
      width: 100%;
    }

    .run-preview-cards {
      width: 100%;
    }
  }

  .run-toolbar-lead {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    flex: 0 1 340px;
    min-width: 0;
  }

  .run-preview-cards {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 480px));
    gap: 10px;
    flex: 0 1 auto;
    min-width: 0;
    max-width: 100%;
    align-content: stretch;
    align-self: stretch;
    box-sizing: border-box;
    min-height: 0;
  }

  /* With two columns and a definite row height (from sibling stretch), 1fr lets both preview tiles fill equal height. */
  @media (min-width: 641px) {
    .run-preview-cards {
      grid-template-rows: 1fr;
    }
  }

  @media (max-width: 640px) {
    .run-preview-cards {
      grid-template-columns: 1fr;
      width: 100%;
      max-width: none;
    }
  }

  .run-preview-card-text {
    margin: 0;
    font-size: 13px;
    line-height: 1.35;
    color: var(--foreground, #0f172a);
    overflow-wrap: break-word;
    word-break: break-word;
    white-space: pre-wrap;
    flex: 1 1 auto;
    min-height: 0;
  }

  .run-title-avatar {
    width: 40px;
    height: 40px;
    border-radius: 999px;
    object-fit: cover;
    flex-shrink: 0;
    box-shadow: inset 0 0 0 1px color-mix(in srgb, #000 10%, transparent);
  }

  .run-title-avatar--placeholder {
    background: color-mix(in srgb, var(--muted-foreground, #64748b) 18%, transparent);
  }

  .run-title-block {
    min-width: 0;
    flex: 1 1 auto;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .run-title-top {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: 8px 14px;
    min-width: 0;
  }

  .run-title-sub {
    margin: 0;
    font-size: 13px;
    line-height: 1.3;
    color: var(--muted-foreground, #64748b);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .run-title-runid {
    margin: 0;
    font-size: 11px;
    line-height: 1.3;
    color: var(--muted-foreground, #64748b);
    overflow: hidden;
    text-overflow: ellipsis;
    word-break: break-all;
  }

  .title-langsmith-link {
    flex-shrink: 0;
    border: 1px solid var(--border, #d4d4d8);
    border-radius: 6px;
    color: var(--primary, #0369a1);
    font-size: 12px;
    padding: 4px 8px;
    text-decoration: none;
    white-space: nowrap;
  }

  .title-langsmith-link:hover {
    background: color-mix(in srgb, var(--primary, #0369a1) 8%, transparent);
  }

  .run-status-dot {
    width: 11px;
    height: 11px;
    border-radius: 999px;
    flex-shrink: 0;
    box-shadow: inset 0 0 0 1px color-mix(in srgb, #000 12%, transparent);
  }

  .run-status-dot[data-status='completed'] {
    background: #22c55e;
  }

  .run-status-dot[data-status='failed'] {
    background: #ef4444;
  }

  .run-status-dot[data-status='cancelled'] {
    background: #f97316;
  }

  .run-status-dot[data-status='skipped'] {
    background: #a855f7;
  }

  .run-status-dot[data-status='unknown'] {
    background: #94a3b8;
  }

  .run-status-dot[data-status='other'] {
    background: #3b82f6;
  }

  .run-elapsed-total-inner {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    justify-content: space-between;
    gap: 12px 20px;
    width: 100%;
    min-width: 0;
  }

  .run-toolbar-elapsed,
  .run-toolbar-cost {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    justify-content: center;
    gap: 2px;
  }

  .run-toolbar-metric-label {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--muted-foreground, #64748b);
  }

  .run-toolbar-elapsed-value {
    font-size: 22px;
    font-weight: 600;
    line-height: 1.1;
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.02em;
    color: #059669;
  }

  :global(.dark) .run-toolbar-elapsed-value {
    color: #34d399;
  }

  .run-toolbar-cost-value {
    font-size: 22px;
    font-weight: 600;
    line-height: 1.1;
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.02em;
    color: #7c3aed;
  }

  :global(.dark) .run-toolbar-cost-value {
    color: #a78bfa;
  }

  .run-detail-title {
    margin: 0;
    font-size: 18px;
    font-weight: 600;
    line-height: 1.2;
    font-family: inherit;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* Aggregate row: token/model dashboard cards, then remaining ledger fields. */

  .run-aggregate-dashboard {
    min-width: 0;
  }

  .run-metric-cards {
    display: grid;
    grid-template-columns: minmax(0, 1.35fr) minmax(0, 0.9fr) minmax(0, 1.25fr);
    gap: 10px;
    align-items: stretch;
  }

  @media (max-width: 1100px) {
    .run-metric-cards {
      grid-template-columns: 1fr;
    }
  }

  .run-metric-card--tokens {
    gap: 10px;
  }

  .run-metric-card--speech {
    gap: 10px;
  }

  .run-speech-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px 12px;
    align-items: start;
  }

  @media (max-width: 520px) {
    .run-metric-card--speech {
      overflow-x: auto;
      padding-bottom: 4px;
    }

    .run-speech-grid {
      grid-template-columns: repeat(3, minmax(88px, 1fr));
      min-width: min(100%, 320px);
    }
  }

  .run-metric-stat-heading {
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 0;
  }

  .run-metric-stat-kicker {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    text-decoration: none;
    color: var(--foreground, #0f172a);
    cursor: help;
  }

  .run-metric-stat-desc {
    font-size: 9px;
    font-weight: 500;
    line-height: 1.25;
    letter-spacing: 0.01em;
    text-transform: none;
    color: var(--muted-foreground, #64748b);
  }

  .run-token-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 8px 12px;
    align-items: start;
  }

  @media (max-width: 520px) {
    .run-metric-card--tokens {
      overflow-x: auto;
      padding-bottom: 4px;
    }

    .run-token-grid {
      grid-template-columns: repeat(4, minmax(64px, 1fr));
      min-width: min(100%, 280px);
    }
  }

  .run-token-stat {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
  }

  .run-token-stat-label {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: var(--muted-foreground, #64748b);
  }

  .run-token-stat-value {
    font-size: 18px;
    font-weight: 600;
    line-height: 1.15;
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.02em;
    color: var(--foreground, #0f172a);
  }

  .run-metric-card {
    display: flex;
    flex-direction: column;
    gap: 6px;
    min-width: 0;
    padding: 10px 12px;
    border: 1px solid var(--border, #e4e4e7);
    border-radius: 8px;
    background: color-mix(in srgb, var(--muted-foreground, #64748b) 6%, transparent);
  }

  .run-metric-card.run-metric-card--preview {
    gap: 8px;
    min-height: 0;
    height: 100%;
    justify-content: flex-start;
  }

  .run-metric-card.run-metric-card--elapsed-total {
    flex: 0 1 auto;
    gap: 10px;
    min-width: min(100%, 200px);
    max-width: 100%;
    align-self: stretch;
    justify-content: center;
    box-sizing: border-box;
  }

  .run-metric-card-label {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--muted-foreground, #64748b);
  }

  .run-metric-card-model {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
  }

  .run-metric-card-model-line {
    font-size: 12px;
    line-height: 1.3;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .run-metric-card-model-id {
    font-size: 13px;
    font-weight: 600;
  }

  /* Run aggregate: one labeled cell per ledger column (why: operator sees entire CSV row without duplication in node grid). */

  .run-header-grid {
    display: grid;
    /* Three dt/dd pairs per row: label constrained, values share remaining space. */
    grid-template-columns: repeat(3, max-content minmax(0, 1fr));
    gap: 6px 14px;
    margin: 0;
    padding: 12px;
    border: 1px solid var(--border, #e4e4e7);
    border-radius: 8px;
    background: color-mix(in srgb, var(--muted-foreground, #64748b) 6%, transparent);
    font-size: 11px;
  }

  .run-header-grid dt {
    margin: 0;
    color: var(--muted-foreground, #64748b);
    font-weight: 600;
    text-transform: capitalize;
    word-break: break-word;
    grid-column: auto;
  }

  .run-header-grid dd {
    margin: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    grid-column: auto;
    color: var(--foreground, inherit);
    white-space: pre-wrap;
    word-break: break-word;
    max-height: 4.8em;
    line-height: 1.2em;
  }

  .mono {
    font-family:
      ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono', 'Courier New', monospace;
  }

  .warn {
    padding: 10px;
    border-radius: 8px;
    border: 1px solid color-mix(in srgb, #f97316 40%, transparent);
    background: color-mix(in srgb, #f97316 10%, transparent);
    color: var(--foreground, #0f172a);
    font-size: 13px;
  }

  .placeholder-row td {
    text-align: center;
    color: var(--muted-foreground, #64748b);
    white-space: normal;
    padding: 16px;
  }

  .error {
    color: var(--muted-foreground, #64748b);
  }
</style>
