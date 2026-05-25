/**
 * Side-effect-free helpers for Graph Runs admin UI (ledger list, run detail, Mem0 pane).
 * Kept separate from GraphRunsPage.svelte so formatting and parsing stay unit-testable.
 */
import { base } from '$app/paths';
import type { ChatChannelRow } from '$lib/api/chat-channels';
import type { CharacterRow } from '$lib/api/characters';
import type { GraphLedgerRow } from '$lib/api/graph-runs';
import {
  formatAgentElapsedMs,
  formatTokenCount,
  formatUsdCostDisplay
} from '$lib/features/chat-channels/messages/agent-message-meta';
import { formatChatTimestamp } from '$lib/features/chat-channels/chat-datetime';

/** Admin logs search scopes by ``msg_id``, same value as ledger ``inbound_id`` (see docs/feedback.md). */
export function adminLogsUrlForInboundId(inboundId: string): string {
  const mid = String(inboundId ?? '').trim();
  return `${base}/logs?msg_id=${encodeURIComponent(mid)}`;
}

/**
 * Normalizes aggregate `status` for the toolbar dot (toolbar carries previews; grid omits status).
 * Add new branches here if the ledger introduces more terminal status slugs.
 */
export function runStatusDataValue(status: string): string {
  const s = String(status || '').trim().toLowerCase();
  if (s === 'completed') return 'completed';
  if (s === 'failed') return 'failed';
  if (s === 'cancelled' || s === 'canceled') return 'cancelled';
  if (s === 'skipped') return 'skipped';
  if (!s) return 'unknown';
  return 'other';
}

export const RUNS_TAB = 'runs' as const;
export const MEMORIES_TAB = 'memories' as const;
export type ActivePane = typeof RUNS_TAB | typeof MEMORIES_TAB | string;

/** Standalone knowledge answer runs written by ``KnowledgeService.answer``. */
export const KNOWLEDGE_RUN_ID_PREFIX = 'knowledge-';

export const CHAT_RUN_ID_PREFIX = 'chat-';

export type GraphRunKindFilter = '' | 'chat' | 'knowledge';

export function isKnowledgeStandaloneRun(runId: string): boolean {
  return String(runId ?? '').trim().startsWith(KNOWLEDGE_RUN_ID_PREFIX);
}

export function isChatAgentRun(runId: string): boolean {
  return String(runId ?? '').trim().startsWith(CHAT_RUN_ID_PREFIX);
}

export function graphRunKindLabel(runId: string): string {
  if (isKnowledgeStandaloneRun(runId)) return 'Knowledge';
  if (isChatAgentRun(runId)) return 'Chat';
  return 'Other';
}

export function graphRunKindMatchesFilter(runId: string, filter: GraphRunKindFilter): boolean {
  if (!filter) return true;
  if (filter === 'knowledge') return isKnowledgeStandaloneRun(runId);
  if (filter === 'chat') return isChatAgentRun(runId);
  return true;
}

export function isGraphNodeSubstep(nodeName: string): boolean {
  const node = String(nodeName ?? '');
  return node.startsWith('tools/') || node.startsWith('knowledge/');
}

/** A11y — primary pills: workspace (graph runs subtree) vs Mem0 pane. */
export const GRAPH_RUNS_PRIMARY_TAB_IDS = {
  runsWorkspace: 'graph-runs-tab-primary-runs',
  memories: 'graph-runs-tab-primary-memories'
} as const;

/** Secondary strip: ledger list vs opened run inspectors (shown only inside graph runs workspace). */
export const GRAPH_RUNS_SUBTAB_IDS = {
  browse: 'graph-runs-subtab-browse-list'
} as const;

export const GRAPH_RUNS_PRIMARY_TABLIST_LABEL =
  'Switch between Graph runs and Memories';

/** Second-level tabs under the subtitle (browse vs open run inspectors). */
export const GRAPH_RUNS_SUBTAB_TABLIST_LABEL = 'Ledger and opened runs';

export const GRAPH_RUNS_PANEL_IDS = {
  runs: 'graph-runs-panel-runs',
  memories: 'graph-runs-panel-memories',
  detail: 'graph-runs-panel-detail'
} as const;

/** First summary card: show at most this many characters of ``run_id`` (full id stays on hover). */
export const RUN_ID_FIRST_CARD_CHARS = 15;

/** HTML id fragment from run id (ledger ids may include characters unsafe for DOM ids). */
export function graphRunTabId(runId: string): string {
  return `graph-runs-tab-open-${runId.replace(/[^a-zA-Z0-9_-]/g, '_')}`;
}

/** Deep-link into Graph Runs with a specific run tab open. */
export function graphRunPageUrl(runId: string): string {
  const trimmed = String(runId ?? '').trim();
  if (!trimmed) return '/graph-runs/';
  return `/graph-runs/?run=${encodeURIComponent(trimmed)}`;
}

/** Run-detail tabs only — not the ledger list or Mem0 pane. */
export function isRunDetailPane(pane: ActivePane): boolean {
  return pane !== RUNS_TAB && pane !== MEMORIES_TAB;
}

const logDateShort = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric' });
const logTime12h = new Intl.DateTimeFormat(undefined, {
  hour: 'numeric',
  minute: '2-digit',
  second: '2-digit',
  hour12: true
});

/** Short column titles for ledger keys (dense tables). */
export function fieldLabel(field: keyof GraphLedgerRow): string {
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
export function graphCostCell(n: number): string {
  const label = formatUsdCostDisplay(n);
  if (label) return label;
  if (n === 0) return '$0.00';
  return '—';
}

export function listRowCharacter(
  row: GraphLedgerRow,
  characterMap: Record<string, CharacterRow>,
  channelById: Map<number, ChatChannelRow>
): { name: string; photo: string | null } {
  if (isKnowledgeStandaloneRun(String(row.run_id ?? ''))) {
    return { name: 'Knowledge', photo: null };
  }
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

export function listRowChannelName(row: GraphLedgerRow, channelById: Map<number, ChatChannelRow>): string {
  if (isKnowledgeStandaloneRun(String(row.run_id ?? ''))) {
    return 'Admin';
  }
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
export function highlightPreviewSegments(
  text: string,
  needleLower: string
): { text: string; hit: boolean }[] {
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
export function trimRunIdForList(runId: string): string {
  const s = String(runId || '').trim();
  if (s.length <= 18) return s;
  return `${s.slice(0, 10)}…${s.slice(-6)}`;
}

export function formatLedgerField(field: keyof GraphLedgerRow, row: GraphLedgerRow): string {
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

export function memoryPrimaryText(m: Record<string, unknown>): string {
  const raw = m.memory ?? m.text ?? m.content ?? m['data'];
  if (typeof raw === 'string') return raw;
  if (raw !== null && typeof raw === 'object') return JSON.stringify(raw);
  return raw === null || raw === undefined ? '' : String(raw);
}

export function memoryStableKey(m: Record<string, unknown>, index: number): string {
  const id = m.id ?? m.memory_id;
  if (typeof id === 'string' && id.length > 0) return id;
  if (typeof id === 'number' && Number.isFinite(id)) return String(id);
  return `mem-${index}`;
}

export function memoryId(row: Record<string, unknown>): string {
  const raw = row.id ?? row.memory_id;
  return raw === null || raw === undefined ? '' : String(raw).trim();
}

export function memoryMetadata(row: Record<string, unknown>): Record<string, unknown> {
  const metadata = row.metadata;
  return metadata && typeof metadata === 'object' && !Array.isArray(metadata)
    ? (metadata as Record<string, unknown>)
    : {};
}

export function memoryField(row: Record<string, unknown>, ...keys: string[]): unknown {
  const metadata = memoryMetadata(row);
  for (const key of keys) {
    const direct = row[key];
    if (direct !== null && direct !== undefined && direct !== '') return direct;
    const meta = metadata[key];
    if (meta !== null && meta !== undefined && meta !== '') return meta;
  }
  return null;
}

export function parseMemoryDate(value: unknown): Date | null {
  if (value === null || value === undefined || value === '') return null;
  if (typeof value === 'number' && Number.isFinite(value)) {
    const ms = value > 10_000_000_000 ? value : value * 1000;
    const d = new Date(ms);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  const numeric = Number(trimmed);
  if (Number.isFinite(numeric)) return parseMemoryDate(numeric);
  const d = new Date(trimmed);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function memoryUpdatedRaw(row: Record<string, unknown>): unknown {
  return memoryField(row, 'updated_at', 'updatedAt', 'updated');
}

export function memoryCreatedRaw(row: Record<string, unknown>): unknown {
  return memoryField(row, 'created_at', 'createdAt', 'created');
}

export function memorySortSeconds(row: Record<string, unknown>): number {
  const updated = parseMemoryDate(memoryUpdatedRaw(row));
  const created = parseMemoryDate(memoryCreatedRaw(row));
  return (updated ?? created)?.getTime() ?? 0;
}

export function memoryDateDisplay(value: unknown): { date: string; time: string; title: string } {
  const d = parseMemoryDate(value);
  if (!d) return { date: '—', time: '—', title: '' };
  return {
    date: logDateShort.format(d),
    time: logTime12h.format(d),
    title: d.toLocaleString()
  };
}

export function memoryChannelId(row: Record<string, unknown>): number | null {
  const raw = memoryField(row, 'channel_id', 'chat_channel_id');
  if (typeof raw === 'number' && Number.isFinite(raw) && raw > 0) return raw;
  if (typeof raw === 'string') {
    const numeric = Number(raw.trim());
    if (Number.isFinite(numeric) && numeric > 0) return numeric;
  }
  return null;
}

export function memoryChannel(
  row: Record<string, unknown>,
  channelById: Map<number, ChatChannelRow>
): ChatChannelRow | undefined {
  const id = memoryChannelId(row);
  return id === null ? undefined : channelById.get(id);
}

export function memoryChannelName(
  row: Record<string, unknown>,
  channelById: Map<number, ChatChannelRow>
): string {
  const id = memoryChannelId(row);
  if (id === null) return '—';
  const name = channelById.get(id)?.name?.trim();
  return name || `Channel ${id}`;
}

export function memoryAgentId(row: Record<string, unknown>): string {
  return String(memoryField(row, 'agent_id', 'character_id') ?? '').trim();
}

export function memoryCharacter(
  row: Record<string, unknown>,
  characterMap: Record<string, CharacterRow>,
  channelById: Map<number, ChatChannelRow>
): { name: string; photo: string | null } {
  const agentId = memoryAgentId(row);
  const ch = memoryChannel(row, channelById);
  const character = agentId ? characterMap[agentId] : undefined;
  const name = character?.name?.trim() || ch?.character?.name?.trim() || (agentId || '—');
  const photo = character?.photo_data_url || ch?.photo_data_url || null;
  return { name, photo };
}

export function memorySharedLabel(row: Record<string, unknown>): string {
  const raw = memoryField(row, 'shared');
  if (typeof raw === 'boolean') return raw ? 'Yes' : 'No';
  if (typeof raw === 'string') {
    const lower = raw.trim().toLowerCase();
    if (['true', '1', 'yes'].includes(lower)) return 'Yes';
    if (['false', '0', 'no'].includes(lower)) return 'No';
  }
  return '—';
}

export function memorySourceLabel(row: Record<string, unknown>): string {
  const source = String(memoryField(row, 'source') ?? '').trim();
  return source || '—';
}

/** Case-insensitive substring match across common memory row fields (Memories tab search). */
export function memoryRowMatchesSearchNeedle(
  row: Record<string, unknown>,
  needleLower: string,
  characterMap: Record<string, CharacterRow>,
  channelById: Map<number, ChatChannelRow>
): boolean {
  if (!needleLower) return true;
  const primary = memoryPrimaryText(row).toLowerCase();
  const id = memoryId(row).toLowerCase();
  const src = String(memoryField(row, 'source') ?? '').toLowerCase();
  const chName = memoryChannelName(row, channelById).toLowerCase();
  const charName = memoryCharacter(row, characterMap, channelById).name.toLowerCase();
  return (
    primary.includes(needleLower) ||
    id.includes(needleLower) ||
    src.includes(needleLower) ||
    chName.includes(needleLower) ||
    charName.includes(needleLower)
  );
}

export type MemoryRowFilterOpts = {
  characterId: string;
  channelId: string;
  sourceFilter: string;
  searchNeedle: string;
  characterMap: Record<string, CharacterRow>;
  channelById: Map<number, ChatChannelRow>;
};

export function memoryRowPassesFilters(row: Record<string, unknown>, opts: MemoryRowFilterOpts): boolean {
  const charF = opts.characterId.trim();
  if (charF && memoryAgentId(row) !== charF) return false;

  const chanF = opts.channelId.trim();
  if (chanF) {
    const n = Number(chanF);
    if (!Number.isFinite(n) || memoryChannelId(row) !== n) return false;
  }

  const srcF = opts.sourceFilter;
  if (srcF === '__empty__') {
    if (String(memoryField(row, 'source') ?? '').trim() !== '') return false;
  } else if (srcF.trim()) {
    const rowSrc = String(memoryField(row, 'source') ?? '').trim();
    if (rowSrc !== srcF.trim()) return false;
  }

  if (opts.searchNeedle && !memoryRowMatchesSearchNeedle(row, opts.searchNeedle, opts.characterMap, opts.channelById)) {
    return false;
  }
  return true;
}

export function formatCost(value: number | ''): string {
  if (value === '') return '—';
  const n = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(n)) return '—';
  return graphCostCell(n);
}

/** Duration / fractional seconds — ledger STT/TTS audio fields. */
export function formatSecondsCardValue(raw: number | ''): string {
  if (raw === '' || raw === null || raw === undefined) return '—';
  const n = typeof raw === 'number' ? raw : Number(raw);
  if (!Number.isFinite(n)) return '—';
  return `${n.toFixed(3)} s`;
}

/** Token totals on aggregate row — tiered counts match chat ``AgentTokenCounter``. */
export function formatTokenCardValue(raw: number | ''): string {
  if (raw === '' || raw === null || raw === undefined) return '—';
  const n = typeof raw === 'number' ? raw : Number(raw);
  if (!Number.isFinite(n)) return '—';
  return formatTokenCount(Math.max(0, Math.trunc(n)));
}
