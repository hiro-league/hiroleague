import { describe, expect, it } from 'vitest';
import type { ChatChannelRow } from '$lib/api/chat-channels';
import type { CharacterRow } from '$lib/api/characters';
import {
  DEFAULT_MEMORY_SORT,
  memoryAgentId,
  memoryChannelId,
  memoryChannelName,
  memoryCharacter,
  memoryChunkIds,
  memoryCreatedRaw,
  memoryDateInputMs,
  memoryEntities,
  memoryField,
  memoryGroupId,
  memoryId,
  memoryKind,
  memoryKindLabel,
  memoryMetadata,
  memoryPrimaryText,
  memoryRowMatchesSearch,
  memoryRowPassesFilters,
  memorySharedLabel,
  memorySortSeconds,
  memorySourceLabel,
  memorySourceOptions,
  memoryStableKey,
  memoryValidity,
  sortMemories
} from './memory-pure';

type Row = Record<string, unknown>;

// A timestamp comfortably in the "milliseconds" range (> 1e10) so the flexible
// parser does not multiply it by 1000.
const MS_2023 = 1_700_000_000_000;
const MS_2024 = 1_710_000_000_000;

function character(p: Partial<CharacterRow> = {}): CharacterRow {
  return { id: 'c1', name: 'Ada', photo_data_url: 'data:ada', ...p } as CharacterRow;
}

function channel(p: Partial<ChatChannelRow> = {}): ChatChannelRow {
  return { id: 1, name: 'General', ...p } as ChatChannelRow;
}

describe('memoryPrimaryText', () => {
  it('prefers memory, then text/content/data', () => {
    expect(memoryPrimaryText({ memory: 'a', text: 'b' })).toBe('a');
    expect(memoryPrimaryText({ text: 'b' })).toBe('b');
    expect(memoryPrimaryText({ content: 'c' })).toBe('c');
    expect(memoryPrimaryText({ data: 'd' })).toBe('d');
  });

  it('stringifies object payloads and handles empty', () => {
    expect(memoryPrimaryText({ memory: { a: 1 } })).toBe('{"a":1}');
    expect(memoryPrimaryText({})).toBe('');
  });

  it('falls back to the entity name for a bare entity with no summary', () => {
    // kind="entity" rows carry an empty memory — show the entity name instead of a blank cell.
    expect(memoryPrimaryText({ kind: 'entity', memory: '', entity_name: 'Ada' })).toBe('Ada');
    // A summarized row keeps its summary text.
    expect(memoryPrimaryText({ kind: 'summary', memory: 'turned 50', entity_name: 'Ada' })).toBe(
      'turned 50'
    );
  });
});

describe('memoryStableKey', () => {
  it('uses id / memory_id when present, else falls back to index', () => {
    expect(memoryStableKey({ id: 'x' }, 0)).toBe('x');
    expect(memoryStableKey({ memory_id: 42 }, 0)).toBe('42');
    expect(memoryStableKey({}, 7)).toBe('mem-7');
  });
});

describe('memoryId', () => {
  it('trims and falls back to memory_id, empty when absent', () => {
    expect(memoryId({ id: '  abc ' })).toBe('abc');
    expect(memoryId({ memory_id: 5 })).toBe('5');
    expect(memoryId({})).toBe('');
  });
});

describe('memoryMetadata', () => {
  it('returns the object metadata or an empty object', () => {
    expect(memoryMetadata({ metadata: { k: 1 } })).toEqual({ k: 1 });
    expect(memoryMetadata({ metadata: [1, 2] })).toEqual({});
    expect(memoryMetadata({})).toEqual({});
  });
});

describe('memoryField', () => {
  it('reads a top-level key first', () => {
    expect(memoryField({ source: 'top' }, 'source')).toBe('top');
  });

  it('falls back to metadata when the top-level value is empty/missing', () => {
    expect(memoryField({ metadata: { source: 'meta' } }, 'source')).toBe('meta');
    expect(memoryField({ source: '', metadata: { source: 'meta' } }, 'source')).toBe('meta');
  });

  it('honours key order and returns null when nothing matches', () => {
    expect(memoryField({ b: 'second' }, 'a', 'b')).toBe('second');
    expect(memoryField({}, 'a', 'b')).toBeNull();
  });
});

describe('memorySortSeconds', () => {
  it('prefers updated over created and returns 0 when undated', () => {
    expect(memorySortSeconds({ updated_at: MS_2024, created_at: MS_2023 })).toBe(MS_2024);
    expect(memorySortSeconds({ created_at: MS_2023 })).toBe(MS_2023);
    expect(memorySortSeconds({})).toBe(0);
  });

  it('reads created via metadata fallback', () => {
    expect(memoryCreatedRaw({ metadata: { created_at: MS_2023 } })).toBe(MS_2023);
  });
});

describe('channel + character resolution', () => {
  it('parses channel id from number or numeric string, ignoring non-positive', () => {
    expect(memoryChannelId({ channel_id: 3 })).toBe(3);
    expect(memoryChannelId({ chat_channel_id: '4' })).toBe(4);
    expect(memoryChannelId({ channel_id: 0 })).toBeNull();
    expect(memoryChannelId({})).toBeNull();
  });

  it('names a channel, falling back to "Channel N" then dash', () => {
    const byId = new Map([[1, channel({ id: 1, name: 'General' })]]);
    expect(memoryChannelName({ channel_id: 1 }, byId)).toBe('General');
    expect(memoryChannelName({ channel_id: 2 }, byId)).toBe('Channel 2');
    expect(memoryChannelName({}, byId)).toBe('—');
  });

  it('reads the agent id from agent_id / character_id', () => {
    expect(memoryAgentId({ agent_id: ' a ' })).toBe('a');
    expect(memoryAgentId({ character_id: 'c1' })).toBe('c1');
    expect(memoryAgentId({})).toBe('');
  });

  it('resolves character name+photo from the character map, then the channel character', () => {
    const charMap = { c1: character({ id: 'c1', name: 'Ada', photo_data_url: 'data:ada' }) };
    const byId = new Map<number, ChatChannelRow>([
      [1, channel({ id: 1, character: { name: 'ChanChar' }, photo_data_url: 'data:chan' } as Partial<ChatChannelRow>)]
    ]);
    expect(memoryCharacter({ agent_id: 'c1' }, charMap, byId)).toEqual({ name: 'Ada', photo: 'data:ada' });
    expect(memoryCharacter({ channel_id: 1 }, {}, byId)).toEqual({ name: 'ChanChar', photo: 'data:chan' });
    expect(memoryCharacter({ agent_id: 'ghost' }, {}, new Map())).toEqual({ name: 'ghost', photo: null });
  });
});

describe('label helpers', () => {
  it('normalizes shared into Yes/No/—', () => {
    expect(memorySharedLabel({ shared: true })).toBe('Yes');
    expect(memorySharedLabel({ shared: 'no' })).toBe('No');
    expect(memorySharedLabel({ shared: '1' })).toBe('Yes');
    expect(memorySharedLabel({})).toBe('—');
  });

  it('returns source or dash', () => {
    expect(memorySourceLabel({ source: ' chat ' })).toBe('chat');
    expect(memorySourceLabel({})).toBe('—');
  });
});

describe('memoryKind', () => {
  it('only accepts relation/summary', () => {
    expect(memoryKind({ kind: 'Relation' })).toBe('relation');
    expect(memoryKind({ kind: 'SUMMARY' })).toBe('summary');
    expect(memoryKind({ kind: 'entity' })).toBe('entity');
    expect(memoryKind({ kind: 'other' })).toBe('');
    expect(memoryKindLabel({ kind: 'relation' })).toBe('Relation');
    expect(memoryKindLabel({ kind: 'summary' })).toBe('Summary');
    expect(memoryKindLabel({ kind: 'entity' })).toBe('Entity');
    expect(memoryKindLabel({})).toBe('—');
  });
});

describe('memoryValidity', () => {
  it('is expired when invalid_at or expired_at is present', () => {
    expect(memoryValidity({ created_at: MS_2023 }).expired).toBe(false);
    expect(memoryValidity({ invalid_at: MS_2024 }).expired).toBe(true);
    expect(memoryValidity({ expired_at: MS_2024 }).expired).toBe(true);
  });

  it('exposes validAt from created_at', () => {
    expect(memoryValidity({ created_at: MS_2023 }).validAt).toBe(MS_2023);
  });
});

describe('memoryEntities', () => {
  it('builds a relation triple, using names then short uuid fallback', () => {
    expect(
      memoryEntities({ kind: 'relation', source_name: 'Ada', relation: 'KNOWS', target_name: 'Bob' })
    ).toEqual({ kind: 'relation', source: 'Ada', relation: 'KNOWS', target: 'Bob' });

    expect(
      memoryEntities({ kind: 'relation', source_id: 'abcdef1234567890', target_id: 'x' })
    ).toEqual({ kind: 'relation', source: 'abcdef12…', relation: '', target: 'x' });
  });

  it('builds a summary entity and returns null when empty', () => {
    expect(memoryEntities({ kind: 'summary', entity_name: 'Ada', entity_type: 'Person' })).toEqual({
      kind: 'summary',
      entity: 'Ada',
      type: 'Person'
    });
    expect(memoryEntities({ kind: 'relation' })).toBeNull();
    expect(memoryEntities({ kind: 'summary' })).toBeNull();
    expect(memoryEntities({})).toBeNull();
  });
});

describe('memoryGroupId + memoryChunkIds', () => {
  it('reads group id from group_id / groupId', () => {
    expect(memoryGroupId({ group_id: ' g1 ' })).toBe('g1');
    expect(memoryGroupId({ metadata: { groupId: 'g2' } })).toBe('g2');
    expect(memoryGroupId({})).toBe('');
  });

  it('returns trimmed, non-empty chunk ids only from arrays', () => {
    expect(memoryChunkIds({ chunk_ids: [' a ', '', 'b', null] })).toEqual(['a', 'b']);
    expect(memoryChunkIds({ chunk_ids: 'nope' })).toEqual([]);
    expect(memoryChunkIds({})).toEqual([]);
  });
});

describe('memoryRowMatchesSearch', () => {
  const charMap = { c1: character({ id: 'c1', name: 'Ada' }) };
  const byId = new Map([[1, channel({ id: 1, name: 'General' })]]);

  it('matches across text, id, source, channel and character names', () => {
    const row: Row = { id: 'mem-1', memory: 'likes coffee', source: 'chat', agent_id: 'c1', channel_id: 1 };
    expect(memoryRowMatchesSearch(row, 'coffee', charMap, byId)).toBe(true);
    expect(memoryRowMatchesSearch(row, 'mem-1', charMap, byId)).toBe(true);
    expect(memoryRowMatchesSearch(row, 'ada', charMap, byId)).toBe(true);
    expect(memoryRowMatchesSearch(row, 'general', charMap, byId)).toBe(true);
    expect(memoryRowMatchesSearch(row, 'absent', charMap, byId)).toBe(false);
    expect(memoryRowMatchesSearch(row, '   ', charMap, byId)).toBe(false);
  });
});

describe('memoryRowPassesFilters', () => {
  const charMap = { c1: character({ id: 'c1', name: 'Ada' }) };
  const byId = new Map([[1, channel({ id: 1, name: 'General' })]]);

  function opts(p: Partial<Parameters<typeof memoryRowPassesFilters>[1]> = {}) {
    return {
      characterId: '',
      sourceFilter: '',
      searchQuery: '',
      dateFromMs: NaN,
      dateToMs: NaN,
      characterMap: charMap,
      channelById: byId,
      ...p
    };
  }

  it('filters by character id', () => {
    expect(memoryRowPassesFilters({ agent_id: 'c1' }, opts({ characterId: 'c1' }))).toBe(true);
    expect(memoryRowPassesFilters({ agent_id: 'c2' }, opts({ characterId: 'c1' }))).toBe(false);
  });

  it('applies an inclusive date range and excludes undated rows when a range is set', () => {
    const row: Row = { created_at: MS_2023 };
    expect(memoryRowPassesFilters(row, opts({ dateFromMs: MS_2023 - 1, dateToMs: MS_2023 + 1 }))).toBe(true);
    expect(memoryRowPassesFilters(row, opts({ dateFromMs: MS_2024 }))).toBe(false);
    expect(memoryRowPassesFilters({}, opts({ dateFromMs: MS_2023 }))).toBe(false);
  });

  it('handles the (no source) sentinel and a specific source', () => {
    expect(memoryRowPassesFilters({ source: '' }, opts({ sourceFilter: '__empty__' }))).toBe(true);
    expect(memoryRowPassesFilters({ source: 'chat' }, opts({ sourceFilter: '__empty__' }))).toBe(false);
    expect(memoryRowPassesFilters({ source: 'chat' }, opts({ sourceFilter: 'chat' }))).toBe(true);
    expect(memoryRowPassesFilters({ source: 'email' }, opts({ sourceFilter: 'chat' }))).toBe(false);
  });

  it('applies the search needle last', () => {
    const row: Row = { memory: 'likes tea', agent_id: 'c1' };
    expect(memoryRowPassesFilters(row, opts({ searchQuery: 'tea' }))).toBe(true);
    expect(memoryRowPassesFilters(row, opts({ searchQuery: 'coffee' }))).toBe(false);
  });
});

describe('memorySourceOptions', () => {
  it('lists distinct sources sorted, with the (no source) sentinel first when needed', () => {
    const rows: Row[] = [
      { source: 'chat' },
      { source: 'email' },
      { source: 'chat' },
      { source: '' },
      {}
    ];
    expect(memorySourceOptions(rows)).toEqual([
      { value: '__empty__', label: '(no source)' },
      { value: 'chat', label: 'chat' },
      { value: 'email', label: 'email' }
    ]);
  });

  it('omits the sentinel when every row has a source', () => {
    expect(memorySourceOptions([{ source: 'chat' }])).toEqual([{ value: 'chat', label: 'chat' }]);
  });
});

describe('memoryDateInputMs', () => {
  it('returns NaN for blank input', () => {
    expect(memoryDateInputMs('')).toBeNaN();
    expect(memoryDateInputMs('   ')).toBeNaN();
  });

  it('parses start-of-day and end-of-day boundaries', () => {
    const start = memoryDateInputMs('2024-03-01');
    const end = memoryDateInputMs('2024-03-01', true);
    expect(end - start).toBe(86_399_999); // one full day minus a millisecond
  });
});

describe('sortMemories', () => {
  const sortOpts = { characterMap: {}, channelById: new Map<number, ChatChannelRow>() };

  it('defaults to most-recent-first', () => {
    const rows: Row[] = [
      { id: 'old', created_at: MS_2023 },
      { id: 'new', created_at: MS_2024 }
    ];
    const sorted = sortMemories(rows, DEFAULT_MEMORY_SORT.column, DEFAULT_MEMORY_SORT.direction, sortOpts);
    expect(sorted.map((r) => r.id)).toEqual(['new', 'old']);
  });

  it('reverses with direction', () => {
    const rows: Row[] = [
      { id: 'old', created_at: MS_2023 },
      { id: 'new', created_at: MS_2024 }
    ];
    expect(sortMemories(rows, 'created', 'asc', sortOpts).map((r) => r.id)).toEqual(['old', 'new']);
  });

  it('sorts by origin (chunk count) and does not mutate the input', () => {
    const rows: Row[] = [
      { id: 'a', chunk_ids: ['x', 'y'] },
      { id: 'b', chunk_ids: [] },
      { id: 'c', chunk_ids: ['z'] }
    ];
    const sorted = sortMemories(rows, 'origin', 'asc', sortOpts);
    expect(sorted.map((r) => r.id)).toEqual(['b', 'c', 'a']);
    expect(rows.map((r) => r.id)).toEqual(['a', 'b', 'c']);
  });

  it('breaks ties deterministically by recency then id', () => {
    const rows: Row[] = [
      { id: 'b', kind: 'relation', created_at: MS_2023 },
      { id: 'a', kind: 'relation', created_at: MS_2023 },
      { id: 'c', kind: 'relation', created_at: MS_2024 }
    ];
    // Same kind → tie → newest first, then id asc among equal timestamps.
    expect(sortMemories(rows, 'kind', 'asc', sortOpts).map((r) => r.id)).toEqual(['c', 'a', 'b']);
  });
});
