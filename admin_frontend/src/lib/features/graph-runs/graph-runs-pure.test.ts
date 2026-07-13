import { describe, expect, it, vi } from 'vitest';

// `$app/paths` is a SvelteKit virtual module; pin `base` to '' so the URL helpers are deterministic.
vi.mock('$app/paths', () => ({ base: '' }));

import type { CharacterRow } from '$lib/api/characters';
import type { ChatChannelRow } from '$lib/api/chat-channels';
import type { GraphLedgerRow } from '$lib/api/graph-runs';
import {
  adminLogsUrlForInboundId,
  fieldLabel,
  filterGraphRunsRows,
  formatCost,
  formatLedgerField,
  formatSecondsCardValue,
  graphRunKindLabel,
  graphRunKindMatchesFilter,
  graphRunPageUrl,
  graphRunTabId,
  isChatAgentRun,
  isGraphIngestRun,
  isGraphNodeSubstep,
  isKnowledgeStandaloneRun,
  isRunDetailPane,
  listRowChannelName,
  listRowCharacter,
  previewMultiline,
  RUNS_TAB,
  runStatusDataValue,
  trimRunIdForList
} from './graph-runs-pure';
import { DISTINCT_EMPTY_VALUE } from '$lib/components/page/table/distinct-options';

const ledger = (p: Partial<GraphLedgerRow> = {}): GraphLedgerRow => p as unknown as GraphLedgerRow;
const character = (p: Partial<CharacterRow> = {}): CharacterRow => p as unknown as CharacterRow;
const channel = (p: Partial<ChatChannelRow> = {}): ChatChannelRow => p as unknown as ChatChannelRow;

describe('runStatusDataValue', () => {
  it('normalizes known terminal slugs (case-insensitive), else other/unknown', () => {
    expect(runStatusDataValue('completed')).toBe('completed');
    expect(runStatusDataValue('FAILED')).toBe('failed');
    expect(runStatusDataValue('canceled')).toBe('cancelled');
    expect(runStatusDataValue('cancelled')).toBe('cancelled');
    expect(runStatusDataValue(' skipped ')).toBe('skipped');
    expect(runStatusDataValue('')).toBe('unknown');
    expect(runStatusDataValue('running')).toBe('other');
  });
});

describe('run-kind predicates', () => {
  it('match their prefixes', () => {
    expect(isKnowledgeStandaloneRun('knowledge-42')).toBe(true);
    expect(isGraphIngestRun('graphiti_ingest-42')).toBe(true);
    expect(isChatAgentRun('chat-42')).toBe(true);
    // An ingest run must NOT count as a knowledge run (prefixes 'knowledge_' vs 'knowledge-').
    expect(isKnowledgeStandaloneRun('graphiti_ingest-42')).toBe(false);
  });
});

describe('graphRunKindLabel', () => {
  it('checks ingest before knowledge so ingest runs read as "Ingest"', () => {
    expect(graphRunKindLabel('graphiti_ingest-1')).toBe('Ingest');
    expect(graphRunKindLabel('knowledge-1')).toBe('Knowledge');
    expect(graphRunKindLabel('chat-1')).toBe('Chat');
    expect(graphRunKindLabel('something-else')).toBe('Other');
  });
});

describe('graphRunKindMatchesFilter', () => {
  it('empty filter matches everything', () => {
    expect(graphRunKindMatchesFilter('chat-1', '')).toBe(true);
  });

  it('matches by kind, and ingest runs do not match the knowledge filter', () => {
    expect(graphRunKindMatchesFilter('graphiti_ingest-1', 'ingest')).toBe(true);
    expect(graphRunKindMatchesFilter('knowledge-1', 'knowledge')).toBe(true);
    expect(graphRunKindMatchesFilter('chat-1', 'chat')).toBe(true);
    expect(graphRunKindMatchesFilter('graphiti_ingest-1', 'knowledge')).toBe(false);
    expect(graphRunKindMatchesFilter('chat-1', 'ingest')).toBe(false);
  });
});

describe('isGraphNodeSubstep', () => {
  it('is true for tools/, knowledge/, memory_recall/ and graphiti_ingest/ node names', () => {
    expect(isGraphNodeSubstep('tools/search')).toBe(true);
    expect(isGraphNodeSubstep('knowledge/recall')).toBe(true);
    expect(isGraphNodeSubstep('memory_recall/turn')).toBe(true);
    expect(isGraphNodeSubstep('memory_recall/search')).toBe(true);
    expect(isGraphNodeSubstep('memory_recall/rerank')).toBe(true);
    expect(isGraphNodeSubstep('memory_recall/answer')).toBe(true);
    // Graphiti ingest rows (episode + per-operation) nest under memory_ingest / a KB ingest run.
    expect(isGraphNodeSubstep('graphiti_ingest/episode')).toBe(true);
    expect(isGraphNodeSubstep('graphiti_ingest/extract_entities')).toBe(true);
    expect(isGraphNodeSubstep('agent')).toBe(false);
    // The bare parent stays a top-level step (not indented).
    expect(isGraphNodeSubstep('memory_recall')).toBe(false);
  });
});

describe('graphRunTabId', () => {
  it('sanitizes characters unsafe for DOM ids', () => {
    expect(graphRunTabId('chat-12:3/4')).toBe('graph-runs-tab-open-chat-12_3_4');
  });
});

describe('graphRunPageUrl', () => {
  it('builds a deep link, encoding the run id', () => {
    expect(graphRunPageUrl('')).toBe('/logs/?tab=runs');
    expect(graphRunPageUrl('  ')).toBe('/logs/?tab=runs');
    expect(graphRunPageUrl('chat-1 2')).toBe('/logs/?tab=runs&run=chat-1%202');
  });
});

describe('isRunDetailPane', () => {
  it('is true for any pane that is not the ledger list', () => {
    expect(isRunDetailPane(RUNS_TAB)).toBe(false);
    expect(isRunDetailPane('chat-1')).toBe(true);
  });
});

describe('fieldLabel', () => {
  it('uses the short map, else humanizes the field name', () => {
    expect(fieldLabel('ts')).toBe('Time');
    expect(fieldLabel('run_id')).toBe('Run');
    expect(fieldLabel('elapsed_ms')).toBe('elapsed_ms');
    expect(fieldLabel('reasoning_tokens')).toBe('Reasoning');
    // unmapped → underscores become spaces
    expect(fieldLabel('schema_version' as keyof GraphLedgerRow)).toBe('schema version');
  });
});

describe('trimRunIdForList', () => {
  it('keeps short ids, elides long ones', () => {
    expect(trimRunIdForList('chat-123')).toBe('chat-123');
    expect(trimRunIdForList('graphiti_ingest-abcdef123456')).toBe('graphiti_i…123456');
  });
});

describe('previewMultiline', () => {
  it('breaks the joined preview onto separate lines', () => {
    expect(previewMultiline('a · b | c')).toBe('a\nb\nc');
    expect(previewMultiline('')).toBe('');
  });
});

describe('formatCost / formatSecondsCardValue guards', () => {
  it('dash empties and non-finite', () => {
    expect(formatCost('')).toBe('—');
    expect(formatSecondsCardValue('')).toBe('—');
    expect(formatSecondsCardValue(1.23456)).toBe('1.235 s');
  });
});

describe('formatLedgerField', () => {
  it('dashes empty/nullish raw values', () => {
    expect(formatLedgerField('node', ledger({ node: '' }))).toBe('—');
  });

  it('renders nested step.sub for step_index, plain step otherwise', () => {
    expect(formatLedgerField('step_index', ledger({ step_index: 4, sub_step: 1 }))).toBe('4.1');
    expect(formatLedgerField('step_index', ledger({ step_index: 4, sub_step: '' }))).toBe('4');
  });

  it('fixes audio-seconds to 3 decimals and passes scalars through', () => {
    expect(formatLedgerField('stt_audio_seconds', ledger({ stt_audio_seconds: 1.23456 }))).toBe('1.235');
    expect(formatLedgerField('node', ledger({ node: 'agent' }))).toBe('agent');
  });
});

describe('listRowCharacter / listRowChannelName', () => {
  const charMap: Record<string, CharacterRow> = {
    c1: character({ id: 'c1', name: 'Alice', photo_data_url: 'data:img' })
  };
  const chanById = new Map<number, ChatChannelRow>([
    [7, channel({ id: 7, name: 'General', character_id: 'c1' })]
  ]);

  it('labels standalone ingest/knowledge runs without a character photo', () => {
    expect(listRowCharacter(ledger({ run_id: 'graphiti_ingest-1' }), charMap, chanById)).toEqual({
      name: 'Graph ingest',
      photo: null
    });
    expect(listRowCharacter(ledger({ run_id: 'knowledge-1' }), charMap, chanById)).toEqual({
      name: 'Knowledge',
      photo: null
    });
  });

  it('resolves a chat run to its character name + photo', () => {
    expect(
      listRowCharacter(ledger({ run_id: 'chat-1', character_id: 'c1', chat_channel_id: 7 }), charMap, chanById)
    ).toEqual({ name: 'Alice', photo: 'data:img' });
  });

  it('channel name: Admin for standalone runs, the channel name otherwise, dash when none', () => {
    expect(listRowChannelName(ledger({ run_id: 'knowledge-1' }), chanById)).toBe('Admin');
    expect(listRowChannelName(ledger({ run_id: 'chat-1', chat_channel_id: 7 }), chanById)).toBe('General');
    expect(listRowChannelName(ledger({ run_id: 'chat-1', chat_channel_id: '' }), chanById)).toBe('—');
  });
});

describe('adminLogsUrlForInboundId', () => {
  it('builds the logs deep link with an encoded msg_id', () => {
    expect(adminLogsUrlForInboundId('inb 1')).toBe('/logs?msg_id=inb%201');
  });
});

describe('filterGraphRunsRows', () => {
  it('filters by preview search and status sentinel', () => {
    const rows = [
      { id: '1', ts: 2, status: '', input_preview: 'hello', output_preview: '' },
      { id: '2', ts: 1, status: 'ok', input_preview: 'other', output_preview: '' }
    ] as import('$lib/api/graph-runs').GraphLedgerRow[];
    const filtered = filterGraphRunsRows(rows, {
      gr_q: 'hello',
      gr_char: '',
      gr_chan: '',
      gr_status: '',
      gr_kind: ''
    });
    expect(filtered.map((r) => r.id)).toEqual(['1']);

    const emptyStatus = filterGraphRunsRows(rows, {
      gr_q: '',
      gr_char: '',
      gr_chan: '',
      gr_status: DISTINCT_EMPTY_VALUE,
      gr_kind: ''
    });
    expect(emptyStatus.map((r) => r.id)).toEqual(['1']);
  });
});
