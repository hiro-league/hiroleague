<script lang="ts">
  import { onMount } from 'svelte';
  import { base } from '$app/paths';
  import { ChevronDown, ChevronUp } from '@lucide/svelte';
  import { listChatChannels, type ChatChannelRow } from '$lib/api/chat-channels';
  import { getCharacter, listCharacters, type CharacterDetail, type CharacterRow } from '$lib/api/characters';
  import {
    getGraphRun,
    getGraphRunLangsmithUrl,
    GRAPH_RUN_HEADER_TAB_FIELDS,
    GRAPH_RUN_NODE_TABLE_FIELDS,
    tailGraphRuns,
    type GraphLedgerRow
  } from '$lib/api/graph-runs';
  import {
    formatAgentElapsedMs,
    formatTokenCount,
    formatUsdCostDisplay
  } from '$lib/features/chat-channels/messages/agent-message-meta';
  import { formatChatTimestamp } from '$lib/features/chat-channels/chat-datetime';
  import { PREF_KEYS } from '$lib/preferences/keys';
  import { readLocalBoolean, writeLocalBoolean } from '$lib/preferences/storage';

  /** Admin logs search scopes by ``msg_id``, same value as ledger ``inbound_id`` (see docs/feedback.md). */
  function adminLogsUrlForInboundId(inboundId: string): string {
    const mid = String(inboundId ?? '').trim();
    return `${base}/logs?msg_id=${encodeURIComponent(mid)}`;
  }

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
  let characters = $state<CharacterRow[]>([]);
  let titleCharacter = $state<CharacterDetail | null>(null);

  let error = $state('');
  let offsets: Record<string, number> = {};
  let timer: ReturnType<typeof setInterval> | null = null;

  /** Single-run metric cards row (persisted — first toolbar card stays visible when collapsed). */
  let runDetailCardsExpanded = $state(true);

  /** Nodes timeline table: composite ``GraphLedgerRow.id`` (one selected row max). */
  let selectedNodeRowId = $state<string | null>(null);

  let previewSearch = $state('');
  /** Empty string = all (client-side list filters, same as preview search). */
  let filterCharacterId = $state('');
  let filterChannelId = $state('');
  /** Exact ledger ``status``; ``__empty__`` = rows with blank status; ``''`` = all. */
  let filterStatus = $state('');

  /** Lowercased trimmed query — matches filtering; drives highlight spans in list preview columns. */
  const previewSearchNeedle = $derived(previewSearch.trim().toLowerCase());

  const characterMap = $derived.by((): Record<string, CharacterRow> => {
    const m: Record<string, CharacterRow> = {};
    for (const c of characters) m[c.id] = c;
    return m;
  });

  const channelById = $derived.by((): Map<number, ChatChannelRow> => {
    const m = new Map<number, ChatChannelRow>();
    for (const c of chatChannels) m.set(c.id, c);
    return m;
  });

  const charactersForFilterDropdown = $derived.by(() =>
    [...characters].sort((a, b) => a.name.localeCompare(b.name))
  );

  const channelsForFilterDropdown = $derived.by(() => {
    const cid = filterCharacterId.trim();
    const base = cid
      ? chatChannels.filter((c) => c.character_id === cid)
      : [...chatChannels];
    return base.sort((a, b) => a.name.localeCompare(b.name));
  });

  /** Distinct status values from the current tail buffer (plus synthetic ``__empty__`` when any row lacks status). */
  const statusesForFilterDropdown = $derived.by((): { value: string; label: string }[] => {
    const raw = new Set<string>();
    let anyEmpty = false;
    for (const r of rows) {
      const s = String(r.status ?? '').trim();
      if (s === '') anyEmpty = true;
      else raw.add(s);
    }
    const out: { value: string; label: string }[] = [];
    if (anyEmpty) out.push({ value: '__empty__', label: '(no status)' });
    for (const s of [...raw].sort((a, b) => a.localeCompare(b))) {
      out.push({ value: s, label: s });
    }
    return out;
  });

  const visibleRows = $derived.by(() => {
    const q = previewSearchNeedle;
    const charF = filterCharacterId.trim();
    const chanF = filterChannelId.trim();
    const stF = filterStatus;
    const sorted = [...rows].sort((a, b) => Number(b.ts || 0) - Number(a.ts || 0));
    let filtered = sorted;
    if (charF) {
      filtered = filtered.filter((r) => String(r.character_id ?? '').trim() === charF);
    }
    if (chanF) {
      const n = Number(chanF);
      if (Number.isFinite(n)) {
        filtered = filtered.filter((r) => r.chat_channel_id === n);
      }
    }
    if (stF) {
      if (stF === '__empty__') {
        filtered = filtered.filter((r) => !String(r.status ?? '').trim());
      } else {
        filtered = filtered.filter((r) => String(r.status ?? '').trim() === stF);
      }
    }
    if (q) {
      filtered = filtered.filter((r) => {
        const inp = String(r.input_preview ?? '').toLowerCase();
        const outp = String(r.output_preview ?? '').toLowerCase();
        return inp.includes(q) || outp.includes(q);
      });
    }
    return filtered.slice(0, 500);
  });

  const timeline = $derived(
    activePane === RUNS_TAB ? [] : (timelineByRun[activePane] ?? [])
  );

  /* Narrowing character filter makes the selected channel invalid — clear channel so the table doesn’t go empty silently. */
  $effect(() => {
    const cid = filterCharacterId.trim();
    const chSel = filterChannelId.trim();
    if (!chSel) return;
    const num = Number(chSel);
    if (!Number.isFinite(num)) return;
    const chan = channelById.get(num);
    if (cid && chan && chan.character_id !== cid) {
      filterChannelId = '';
    }
  });

  $effect(() => {
    void timeline;
    if (activePane === RUNS_TAB) return;
    const sid = selectedNodeRowId;
    if (sid !== null && !timeline.some((r) => r.id === sid)) {
      selectedNodeRowId = null;
    }
  });

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

  /** First summary card: show at most this many characters of ``run_id`` (full id stays on hover). */
  const RUN_ID_FIRST_CARD_CHARS = 15;

  const runIdFirstCardDisplay = $derived.by(() => {
    if (activePane === RUNS_TAB) return '';
    const s = String(activePane).trim();
    return s.slice(0, RUN_ID_FIRST_CARD_CHARS);
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
      elapsed_ms: 'elapsed_ms',
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
      reasoning_tokens: 'Reasoning',
      tts_chars: 'TTS chars',
      tts_text_tokens: 'TTS text tok',
      tts_audio_tokens: 'TTS audio tok',
      stt_audio_seconds: 'STT Seconds',
      stt_audio_tokens: 'STT audio tok',
      tts_audio_seconds: 'TTS Seconds',
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

  /** Matches ``AgentTokenCounter`` USD tiers (tieredDecimals in agent-message-meta). */
  function graphCostCell(n: number): string {
    const label = formatUsdCostDisplay(n);
    if (label) return label;
    if (n === 0) return '$0.00';
    return '—';
  }

  function listRowCharacter(row: GraphLedgerRow): { name: string; photo: string | null } {
    const cid = String(row.character_id ?? '').trim();
    const cr = cid ? characterMap[cid] : undefined;
    const chan =
      row.chat_channel_id !== '' && typeof row.chat_channel_id === 'number'
        ? channelById.get(row.chat_channel_id)
        : undefined;
    const name = cr?.name?.trim() || chan?.character?.name?.trim() || (cid || '—');
    const photo = cr?.photo_data_url || chan?.photo_data_url || null;
    return { name, photo };
  }

  function listRowChannelName(row: GraphLedgerRow): string {
    if (row.chat_channel_id === '' || typeof row.chat_channel_id !== 'number') return '—';
    const ch = channelById.get(row.chat_channel_id);
    const n = ch?.name?.trim();
    if (n) return n;
    return `Channel ${row.chat_channel_id}`;
  }

  /**
   * Split preview text into alternating plain / hit slices for ``<mark>`` (case-insensitive).
   * Slices come from the original string so casing in the cell stays as stored in the ledger.
   */
  function highlightPreviewSegments(text: string, needleLower: string): { text: string; hit: boolean }[] {
    const hay = String(text ?? '');
    const hayLower = hay.toLowerCase();
    const out: { text: string; hit: boolean }[] = [];
    let i = 0;
    const nLen = needleLower.length;
    while (i < hay.length) {
      const j = hayLower.indexOf(needleLower, i);
      if (j === -1) {
        if (i < hay.length) out.push({ text: hay.slice(i), hit: false });
        break;
      }
      if (j > i) out.push({ text: hay.slice(i, j), hit: false });
      out.push({ text: hay.slice(j, j + nLen), hit: true });
      i = j + nLen;
    }
    return out;
  }

  /** Trimmed run id for dense tables; full id on control ``title``. */
  function trimRunIdForList(runId: string): string {
    const s = String(runId || '').trim();
    if (s.length <= 18) return s;
    return `${s.slice(0, 10)}…${s.slice(-6)}`;
  }

  /** Same timestamp line as Messages admin (today + clock with seconds). */
  function formatGraphRunsListTs(ts: GraphLedgerRow['ts']): string {
    if (ts === '') return '—';
    const sec = typeof ts === 'number' ? ts : Number(ts);
    if (!Number.isFinite(sec)) return '—';
    return formatChatTimestamp(new Date(sec * 1000).toISOString());
  }

  /** Prompt-side = input + cached (chat agent footer); output = completion tokens. */
  function formatRunListTokensCell(row: GraphLedgerRow): string {
    const inRaw = row.input_tokens;
    const cachedRaw = row.cached_input_tokens;
    const outRaw = row.output_tokens;
    const inN = typeof inRaw === 'number' ? inRaw : Number(inRaw || 0);
    const cachedN = typeof cachedRaw === 'number' ? cachedRaw : Number(cachedRaw || 0);
    const outN = typeof outRaw === 'number' ? outRaw : Number(outRaw || 0);
    const prompt =
      Math.max(0, Math.trunc(Number.isFinite(inN) ? inN : 0)) +
      Math.max(0, Math.trunc(Number.isFinite(cachedN) ? cachedN : 0));
    const completion = Math.max(0, Math.trunc(Number.isFinite(outN) ? outN : 0));
    if (prompt === 0 && completion === 0) return '—';
    /* Order and `` t`` suffix match ``AgentTokenCounter``. */
    return `↑ ${formatTokenCount(prompt)} t · ↓ ${formatTokenCount(completion)} t`;
  }

  function formatLedgerField(field: keyof GraphLedgerRow, row: GraphLedgerRow): string {
    const raw = row[field];
    if (raw === '' || raw === null || raw === undefined) return '—';
    if (field === 'ts') {
      const n = typeof raw === 'number' ? raw : Number(raw);
      /* Match Messages tab clock line (same ``formatChatTimestamp`` path). */
      return Number.isFinite(n) ? formatChatTimestamp(new Date(n * 1000).toISOString()) : String(raw);
    }
    if (field === 'elapsed_ms') {
      const ms = typeof raw === 'number' ? raw : Number(raw);
      if (!Number.isFinite(ms)) return '—';
      const label = formatAgentElapsedMs(Math.trunc(ms));
      return label || '—';
    }
    if (field === 'cost_usd') {
      const n = typeof raw === 'number' ? raw : Number(raw);
      return Number.isFinite(n) ? graphCostCell(n) : String(raw);
    }
    if (
      field === 'input_tokens' ||
      field === 'output_tokens' ||
      field === 'cached_input_tokens' ||
      field === 'reasoning_tokens' ||
      field === 'tts_text_tokens' ||
      field === 'tts_audio_tokens' ||
      field === 'stt_audio_tokens'
    ) {
      const n = typeof raw === 'number' ? raw : Number(raw);
      if (!Number.isFinite(n)) return '—';
      return `${formatTokenCount(Math.max(0, Math.trunc(n)))} t`;
    }
    if (field === 'tts_chars') {
      const n = typeof raw === 'number' ? raw : Number(raw);
      if (!Number.isFinite(n)) return '—';
      return formatTokenCount(Math.max(0, Math.trunc(n)));
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

  async function loadCharacters() {
    const response = await listCharacters();
    if (response.ok && response.data) {
      characters = response.data;
    }
  }

  async function loadInitial() {
    error = '';
    offsets = {};
    const response = await tailGraphRuns({
      lines: 500,
      since_seconds_ago: 86_400
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
      after_offsets: offsets
    });
    if (!response.ok || !response.data) return;
    offsets = response.data.file_offsets;
    if (response.data.rows.length > 0) {
      rows = [...rows, ...response.data.rows].slice(-1000);
    }
  }

  /** LangSmith link loads after ledger inspect — avoids holding node table on upstream API latency. */
  async function resolveLangsmithUrl(runId: string) {
    const res = await getGraphRunLangsmithUrl(runId);
    if (activePane !== runId) return;
    if (res.ok && res.data) {
      langsmithUrlByRun[runId] = res.data.langsmith_url ?? undefined;
    } else {
      langsmithUrlByRun[runId] = undefined;
    }
    langsmithUrlByRun = { ...langsmithUrlByRun };
  }

  async function loadRunDetail(runId: string) {
    langsmithUrlByRun[runId] = undefined;
    langsmithUrlByRun = { ...langsmithUrlByRun };
    const response = await getGraphRun(runId);
    if (response.ok && response.data) {
      timelineByRun[runId] = response.data.rows;
      aggregateByRun[runId] = response.data.aggregate ?? null;
      timelineByRun = { ...timelineByRun };
      aggregateByRun = { ...aggregateByRun };
      void resolveLangsmithUrl(runId);
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
    const alreadyOpen = openRunIds.includes(runId);
    if (!alreadyOpen) {
      openRunIds = [...openRunIds, runId];
    }
    activePane = runId;
    selectedNodeRowId = null;
    /* First open only: re-running inspect clears cached LangSmith URL and refetches upstream — skip when switching back to an open tab. */
    if (!alreadyOpen) {
      await loadRunDetail(runId);
    }
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
    selectedNodeRowId = null;
  }

  function showRunsOnly() {
    activePane = RUNS_TAB;
    selectedNodeRowId = null;
  }

  /** Click again on the selected row clears selection — matches toggle affordance users expect from list UIs. */
  function toggleNodeRowSelection(compositeRowId: string) {
    selectedNodeRowId = selectedNodeRowId === compositeRowId ? null : compositeRowId;
  }

  /**
   * Open-run tab label: show ``input_preview`` (ellipsis via ``.tab-main`` within ``.tab-run`` max-width).
   * Same resolution order as toolbar identity — inspect aggregate, tail run row, then timeline.
   */
  function runSourceRowForOpenTab(runId: string): GraphLedgerRow | null {
    const fromInspect = aggregateByRun[runId];
    if (fromInspect) return fromInspect;
    const fromTail = rows.find((r) => r.run_id === runId && String(r.row_kind) === 'run');
    if (fromTail) return fromTail;
    const tl = timelineByRun[runId] ?? [];
    const runRow = tl.find((r) => String(r.row_kind) === 'run');
    if (runRow) return runRow;
    return tl[0] ?? null;
  }

  function runTabDisplayLabel(runId: string): string {
    const row = runSourceRowForOpenTab(runId);
    const preview = String(row?.input_preview ?? '').trim();
    if (preview.length > 0) return preview;
    if (runId.length <= 18) return runId;
    return `${runId.slice(0, 10)}…${runId.slice(-6)}`;
  }

  function runTabTooltip(runId: string): string {
    const row = runSourceRowForOpenTab(runId);
    const preview = String(row?.input_preview ?? '').trim();
    if (preview.length > 0) return `${runId} — ${preview}`;
    return runId;
  }

  function formatCost(value: number | '') {
    if (value === '') return '—';
    const n = typeof value === 'number' ? value : Number(value);
    if (!Number.isFinite(n)) return '—';
    return graphCostCell(n);
  }

  /** Duration / fractional seconds — ledger STT/TTS audio fields. */
  function formatSecondsCardValue(raw: number | ''): string {
    if (raw === '' || raw === null || raw === undefined) return '—';
    const n = typeof raw === 'number' ? raw : Number(raw);
    if (!Number.isFinite(n)) return '—';
    return `${n.toFixed(3)} s`;
  }

  /** Toggle persists — collapsed hides tokens/model/speech + ledger ``dl``; previews and elapsed/cost stay visible. */
  function toggleRunDetailCards() {
    runDetailCardsExpanded = !runDetailCardsExpanded;
    writeLocalBoolean(PREF_KEYS.graphRunsRunDetailCardsExpanded, runDetailCardsExpanded);
  }

  /** Token totals on aggregate row — tiered counts match chat ``AgentTokenCounter``. */
  function formatTokenCardValue(raw: number | ''): string {
    if (raw === '' || raw === null || raw === undefined) return '—';
    const n = typeof raw === 'number' ? raw : Number(raw);
    if (!Number.isFinite(n)) return '—';
    return formatTokenCount(Math.max(0, Math.trunc(n)));
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
    void loadCharacters();
    runDetailCardsExpanded = readLocalBoolean(PREF_KEYS.graphRunsRunDetailCardsExpanded, true);
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
  Single-run tab: one wrapping card row (toolbar + summaries), aggregate dl, node table.
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
    <div class="tab-bar-tabs">
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
          <button type="button" class="tab-main" onclick={() => openRunTab(rid)} title={runTabTooltip(rid)}>
            {runTabDisplayLabel(rid)}
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
    </div>
    {#if activePane !== RUNS_TAB}
      <button
        type="button"
        class="tab-bar-cards-toggle"
        id="run-detail-cards-toggle"
        aria-expanded={runDetailCardsExpanded}
        aria-controls="run-detail-cards-flow"
        aria-label={runDetailCardsExpanded
          ? 'Collapse detailed metrics and ledger fields'
          : 'Expand detailed metrics and ledger fields'}
        title={runDetailCardsExpanded
          ? 'Collapse detailed metrics and ledger fields'
          : 'Expand detailed metrics and ledger fields'}
        onclick={toggleRunDetailCards}
      >
        {#if runDetailCardsExpanded}
          <ChevronUp size={18} strokeWidth={2} aria-hidden="true" />
        {:else}
          <ChevronDown size={18} strokeWidth={2} aria-hidden="true" />
        {/if}
      </button>
    {/if}
  </nav>

  {#if activePane === RUNS_TAB}
    <div class="filters">
      <select
        bind:value={filterCharacterId}
        class="filter-select"
        aria-label="Filter by character"
      >
        <option value="">All characters</option>
        {#each charactersForFilterDropdown as c (c.id)}
          <option value={c.id}>{c.name || c.id}</option>
        {/each}
      </select>
      <select
        bind:value={filterChannelId}
        class="filter-select"
        aria-label="Filter by channel"
      >
        <option value="">All channels</option>
        {#each channelsForFilterDropdown as ch (ch.id)}
          <option value={String(ch.id)}>{ch.name || `Channel ${ch.id}`}</option>
        {/each}
      </select>
      <select bind:value={filterStatus} class="filter-select" aria-label="Filter by status">
        <option value="">All statuses</option>
        {#each statusesForFilterDropdown as st (st.value)}
          <option value={st.value}>{st.label}</option>
        {/each}
      </select>
      <input
        bind:value={previewSearch}
        class="preview-search"
        type="search"
        placeholder="Search input / output previews…"
        autocomplete="off"
      />
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
            <th>Character</th>
            <th>Channel</th>
            <th>Run</th>
            <th>Input</th>
            <th>Output</th>
            <th>Status</th>
            <th>Cost</th>
            <th>Model</th>
            <th>Decision</th>
            <th>Tokens</th>
            <th>Logs</th>
          </tr>
        </thead>
        <tbody>
          {#each visibleRows as row (row.id)}
            {@const listCh = listRowCharacter(row)}
            <tr class:muted-open={openRunIds.includes(row.run_id)}>
              <td>{formatGraphRunsListTs(row.ts)}</td>
              <td class="runs-list-character-cell">
                <div class="runs-list-character-inner">
                  {#if listCh.photo}
                    <img class="runs-list-avatar" src={listCh.photo} alt="" width="32" height="32" />
                  {:else}
                    <div class="runs-list-avatar runs-list-avatar--placeholder" aria-hidden="true"></div>
                  {/if}
                  <span class="runs-list-character-name">{listCh.name}</span>
                </div>
              </td>
              <td class="runs-list-name-cell">{listRowChannelName(row)}</td>
              <td>
                <button type="button" class="link" title={row.run_id} onclick={() => openRunTab(row.run_id)}
                  >{trimRunIdForList(row.run_id)}</button
                >
              </td>
              <td class="preview">
                {#if previewSearchNeedle && String(row.input_preview ?? '').toLowerCase().includes(previewSearchNeedle)}
                  {#each highlightPreviewSegments(String(row.input_preview ?? ''), previewSearchNeedle) as seg, i (`${row.id}-in-${i}`)}
                    {#if seg.hit}<mark class="preview-hit">{seg.text}</mark>{:else}{seg.text}{/if}
                  {/each}
                {:else}
                  {row.input_preview}
                {/if}
              </td>
              <td class="preview">
                {#if previewSearchNeedle && String(row.output_preview ?? '').toLowerCase().includes(previewSearchNeedle)}
                  {#each highlightPreviewSegments(String(row.output_preview ?? ''), previewSearchNeedle) as seg, i (`${row.id}-out-${i}`)}
                    {#if seg.hit}<mark class="preview-hit">{seg.text}</mark>{:else}{seg.text}{/if}
                  {/each}
                {:else}
                  {row.output_preview}
                {/if}
              </td>
              <td>{row.status}</td>
              <td>{formatCost(row.cost_usd)}</td>
              <td>{row.model}</td>
              <td>{row.decision_kind}{row.decision_detail ? `:${row.decision_detail}` : ''}</td>
              <td>{formatRunListTokensCell(row)}</td>
              <td>
                {#if String(row.inbound_id ?? '').trim()}
                  <a
                    class="link"
                    href={adminLogsUrlForInboundId(row.inbound_id)}
                    title="Open Logs scoped to inbound message id (msg_id)"
                    >Logs</a
                  >
                {:else}
                  —
                {/if}
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {:else}
    <div class="run-detail">
      <div
        id="run-detail-cards-flow"
        class="run-detail-cards-flow"
        class:run-detail-cards-flow--collapsed={!runDetailCardsExpanded}
        role="region"
        aria-label="Run summary — previews, timing, metrics, ledger"
      >
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
                {#if String(runIdentitySource?.inbound_id ?? '').trim()}
                  <a
                    class="title-langsmith-link"
                    href={adminLogsUrlForInboundId(String(runIdentitySource?.inbound_id ?? ''))}
                    title="Operational logs filtered to this inbound id (msg_id)"
                    >Logs</a
                  >
                {/if}
              </div>
              {#if runTitleSubtitle}
                <p class="run-title-sub">Channel: {runTitleSubtitle}</p>
              {/if}
              <p class="run-title-runid mono" title={activePane}>{runIdFirstCardDisplay}</p>
            </div>
          </div>
        </div>
        {#if activeRunAggregate}
          <div class="run-metric-card run-metric-card--preview" aria-label="Input preview card">
            <span class="run-metric-card-label">Input preview</span>
            <p class="run-preview-card-text">{activeRunAggregate.input_preview || '—'}</p>
          </div>
          <div class="run-metric-card run-metric-card--preview" aria-label="Output preview card">
            <span class="run-metric-card-label">Output preview</span>
            <p class="run-preview-card-text">{activeRunAggregate.output_preview || '—'}</p>
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
          <div class="run-metric-card run-metric-card--tokens" aria-label="Token usage">
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
          <dl class="run-header-grid">
            {#each headerFieldList as field (field)}
              <dt title={field}>{fieldLabel(field)}</dt>
              <dd class="mono">{formatLedgerField(field, activeRunAggregate)}</dd>
            {/each}
          </dl>
        {/if}
      </div>

      {#if !activeRunAggregate}
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
              <tr
                class="nodes-table__data-row"
                class:nodes-table__data-row--selected={selectedNodeRowId === row.id}
                class:substep={row.node.startsWith('tools/')}
                tabindex="0"
                aria-selected={selectedNodeRowId === row.id ? 'true' : 'false'}
                onclick={() => toggleNodeRowSelection(row.id)}
                onkeydown={(ev) => {
                  if (ev.key !== 'Enter' && ev.key !== ' ') return;
                  ev.preventDefault();
                  toggleNodeRowSelection(row.id);
                }}
              >
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
  input,
  select {
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

  select {
    min-width: 0;
    padding: 8px 10px;
    cursor: pointer;
  }

  .filter-select {
    flex: 0 1 200px;
    min-width: min(100%, 160px);
    max-width: 260px;
  }

  .filters {
    flex-wrap: wrap;
    align-items: center;
  }

  .preview-search {
    flex: 1 1 280px;
    min-width: min(100%, 200px);
    max-width: 480px;
  }

  .runs-list-character-cell {
    max-width: 220px;
    vertical-align: middle;
  }

  .runs-list-character-inner {
    display: flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
  }

  .runs-list-avatar {
    width: 32px;
    height: 32px;
    border-radius: 999px;
    object-fit: cover;
    flex-shrink: 0;
    display: block;
    box-shadow: inset 0 0 0 1px color-mix(in srgb, #000 10%, transparent);
  }

  .runs-list-avatar--placeholder {
    background: color-mix(in srgb, var(--muted-foreground, #64748b) 18%, transparent);
  }

  .runs-list-character-name {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .runs-list-name-cell {
    max-width: 160px;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .tab-bar {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    justify-content: space-between;
    gap: 8px 12px;
    border-bottom: 1px solid var(--border, #d4d4d8);
    padding-bottom: 0;
  }

  .tab-bar-tabs {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: 4px;
    min-width: 0;
    flex: 1 1 auto;
  }

  .tab-bar-cards-toggle {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    align-self: center;
    width: 36px;
    height: 34px;
    margin-bottom: 2px;
    padding: 0;
    border: 1px solid var(--border, #d4d4d8);
    border-radius: 8px;
    background: color-mix(in srgb, var(--muted-foreground, #64748b) 8%, transparent);
    color: var(--foreground, #0f172a);
  }

  .tab-bar-cards-toggle:hover {
    background: color-mix(in srgb, var(--muted-foreground, #64748b) 14%, transparent);
  }

  /* Collapsed: keep toolbar + preview + elapsed/cost; hide tokens/model/speech and aggregate ledger dl. */

  .run-detail-cards-flow--collapsed
    > .run-metric-card:not(.run-metric-card--preview):not(.run-metric-card--elapsed-total),
  .run-detail-cards-flow--collapsed > .run-header-grid {
    display: none;
  }

  /* Full-width row under wrapping metric cards (dt/dd ledger). */

  .run-detail-cards-flow > .run-header-grid {
    flex: 1 1 100%;
    min-width: 0;
    max-width: 100%;
    align-self: stretch;
    box-sizing: border-box;
  }

  .tab-bar-cards-toggle:focus-visible {
    outline: 2px solid var(--ring, var(--primary, #0369a1));
    outline-offset: 2px;
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

  /* Yellow marker highlight (requested over primary tint for search hits). */
  .preview mark.preview-hit {
    background: #fef08a;
    color: inherit;
    padding: 0;
    border-radius: 2px;
    font: inherit;
  }

  :global(:root[data-theme='dark']) .preview mark.preview-hit {
    background: #ca8a04;
    color: #422006;
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

  /* Nodes timeline: hover + select; ``.substep`` = tools/* node tint. */

  .nodes-table tbody tr.nodes-table__data-row {
    cursor: pointer;
    outline: none;
    transition:
      background-color 80ms ease,
      box-shadow 80ms ease;
  }

  .nodes-table tbody tr.nodes-table__data-row.substep {
    background: color-mix(in srgb, var(--primary, #0ea5e9) 8%, transparent);
  }

  .nodes-table tbody tr.nodes-table__data-row:hover:not(.nodes-table__data-row--selected) {
    background: color-mix(in srgb, var(--muted-foreground, #64748b) 12%, transparent);
  }

  .nodes-table tbody tr.nodes-table__data-row.substep:hover:not(.nodes-table__data-row--selected) {
    background: color-mix(in srgb, var(--primary, #0ea5e9) 16%, transparent);
  }

  .nodes-table tbody tr.nodes-table__data-row.nodes-table__data-row--selected {
    background: color-mix(in srgb, var(--primary, #0369a1) 18%, transparent);
    box-shadow: inset 4px 0 0 var(--primary, #0ea5e9);
  }

  .nodes-table tbody tr.nodes-table__data-row.substep.nodes-table__data-row--selected {
    background: color-mix(in srgb, var(--primary, #0369a1) 22%, transparent);
  }

  .nodes-table tbody tr.nodes-table__data-row:focus-visible {
    outline: 2px solid var(--primary, #0369a1);
    outline-offset: -2px;
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

  /* Title strip + previews + elapsed + token/model/speech cards share one flex-wrap lane (fluid, no separate “header row”). */

  .run-detail-cards-flow {
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
    min-width: 0;
    align-self: stretch;
    box-sizing: border-box;
  }

  .run-detail-cards-flow > .run-detail-toolbar {
    flex: 1 1 minmax(260px, 100%);
  }

  /* Siblings in ``run-detail-cards-flow``: grow/wrap together with shared gap. */

  .run-detail-cards-flow > .run-metric-card {
    flex: 1 1 220px;
    max-width: 100%;
    align-self: stretch;
    box-sizing: border-box;
  }

  .run-detail-cards-flow > .run-metric-card--preview {
    flex: 1 1 minmax(200px, 340px);
  }

  .run-detail-cards-flow > .run-metric-card--tokens,
  .run-detail-cards-flow > .run-metric-card--speech {
    flex: 1 1 minmax(260px, 100%);
  }

  .run-toolbar-lead {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    flex: 0 1 340px;
    min-width: 0;
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

  :global(:root[data-theme='dark']) .run-toolbar-elapsed-value {
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

  :global(:root[data-theme='dark']) .run-toolbar-cost-value {
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

  /* Token stats: keep ledger order but allow wrapping instead of a fixed four-column row. */
  .run-token-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 8px 12px;
    align-items: flex-start;
  }

  .run-token-stat {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
    flex: 1 1 5.25rem;
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
    justify-content: flex-start;
  }

  /* Elapsed+cost participates in ``run-detail-cards-flow`` sizing; omit fixed flex-shrink so it wraps like sibling cards. */

  .run-metric-card.run-metric-card--elapsed-total {
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
