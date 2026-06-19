import { describe, expect, it } from 'vitest';
import type { IngestEntityType, IngestTraceStage } from '$lib/api/graph-runs';
import {
  briefName,
  briefType,
  buildEntityTypeMap,
  buildPhases,
  dedupJson,
  dedupMerges,
  extractedEntities,
  groupStages,
  inputView,
  messages,
  outputView,
  parseFactItems,
  prettyOutput,
  resolveFactsView,
  rowsTable,
  stageCount,
  stageMeta,
  stageRank,
  tagBlock,
  toView
} from './ingest-trace-derive';

function stage(p: Partial<IngestTraceStage> = {}): IngestTraceStage {
  return {
    node: 'extract_entities',
    label: 'Extract entities',
    operation: '',
    source: 'llm',
    elapsed_ms: 0,
    input_tokens: 0,
    output_tokens: 0,
    model_id: '',
    meta: {},
    input: [],
    output: null,
    ...p
  };
}

describe('stageRank / groupStages', () => {
  it('ranks known nodes by pipeline order, unknowns last', () => {
    expect(stageRank('extract_entities')).toBe(0);
    expect(stageRank('resolve_facts')).toBeLessThan(stageRank('completion'));
    expect(stageRank('mystery')).toBe(10);
  });

  it('groups stages by node and sorts groups into pipeline order', () => {
    const groups = groupStages([
      stage({ node: 'resolve_facts', label: 'Resolve facts' }),
      stage({ node: 'extract_entities', label: 'Extract entities' }),
      stage({ node: 'resolve_facts', label: 'Resolve facts' })
    ]);
    expect(groups.map((g) => g.node)).toEqual(['extract_entities', 'resolve_facts']);
    // resolve_facts fired twice → one group with two stage refs, idxs preserved.
    expect(groups[1].stages.map((s) => s.idx)).toEqual([0, 2]);
    expect(groups[0].label).toBe('Extract entities');
  });
});

describe('buildPhases', () => {
  it('maps groups into stable phase order with flat idx lists', () => {
    const groups = groupStages([
      stage({ node: 'extract_entities' }),
      stage({ node: 'extract_facts', label: 'Extract facts' }),
      stage({ node: 'summarize_entities', label: 'Summarize' })
    ]);
    const phases = buildPhases(groups);
    expect(phases.map((p) => p.phase)).toEqual(['entities', 'attributes', 'facts']);
    expect(phases.find((p) => p.phase === 'facts')?.idxs).toEqual([1]);
    expect(phases[0].title).toBe('Entities');
    expect(phases[0].hint).toContain('extract');
  });
});

describe('rowsTable / toView', () => {
  it('projects a scalar list to a single value column', () => {
    expect(rowsTable([1, 2, 3])).toEqual({
      kind: 'rows',
      columns: ['value'],
      rows: [{ value: '1' }, { value: '2' }, { value: '3' }]
    });
  });

  it('unions object keys across rows', () => {
    const v = toView([{ a: 1 }, { b: 2 }]);
    expect(v).toMatchObject({ kind: 'rows', columns: ['a', 'b'] });
  });

  it('unwraps a dict whose only field is a list of objects', () => {
    const v = toView({ extracted_entities: [{ name: 'x' }] });
    expect(v).toMatchObject({ kind: 'rows', columns: ['name'] });
  });

  it('renders other dicts as key/value', () => {
    expect(toView({ a: 1, b: 'two' })).toEqual({
      kind: 'kv',
      entries: [
        { key: 'a', value: '1' },
        { key: 'b', value: 'two' }
      ]
    });
  });

  it('handles empties and scalars', () => {
    expect(toView(null)).toEqual({ kind: 'empty' });
    expect(toView([])).toEqual({ kind: 'empty' });
    expect(toView({})).toEqual({ kind: 'empty' });
    expect(toView('hi')).toEqual({ kind: 'scalar', value: 'hi' });
  });
});

describe('messages / inputView', () => {
  it('reads prompt messages only when input is an array', () => {
    expect(messages(stage({ input: [{ role: 'user', content: 'q' }] }))).toHaveLength(1);
    expect(messages(stage({ input: { a: 1 } }))).toEqual([]);
  });

  it('inputView projects a dict input but is empty when messages exist', () => {
    expect(inputView(stage({ input: { a: 1 } }))).toMatchObject({ kind: 'kv' });
    expect(inputView(stage({ input: [{ role: 'user', content: 'q' }] }))).toEqual({ kind: 'empty' });
  });
});

describe('tagBlock / parseFactItems', () => {
  it('extracts a tagged block', () => {
    expect(tagBlock('a<NEW FACT>\n  hello \n</NEW FACT>b', 'NEW FACT')).toBe('hello');
    expect(tagBlock('no tags', 'NEW FACT')).toBe('');
  });

  it('parses idx/fact items in either quote style and unescapes', () => {
    const block = `{'idx': 0, 'fact': 'Alice met Bob'}, {'idx': 1, 'fact': "Bob's car"}, {'idx': 2, 'fact': 'a \\'q\\' b'}`;
    expect(parseFactItems(block)).toEqual([
      { idx: 0, fact: 'Alice met Bob' },
      { idx: 1, fact: "Bob's car" },
      { idx: 2, fact: "a 'q' b" }
    ]);
  });
});

describe('resolveFactsView', () => {
  const prompt = [
    '<NEW FACT>\nAlice works at Acme\n</NEW FACT>',
    "<EXISTING FACTS>\n{'idx': 0, 'fact': 'Alice works at Acme Corp'}, {'idx': 1, 'fact': 'Alice likes tea'}\n</EXISTING FACTS>",
    "<FACT INVALIDATION CANDIDATES>\n{'idx': 2, 'fact': 'Alice works at Globex'}\n</FACT INVALIDATION CANDIDATES>"
  ].join('\n');

  it('joins prompt candidates to the idx verdict output', () => {
    const rfv = resolveFactsView(
      stage({
        node: 'resolve_facts',
        input: [{ role: 'user', content: prompt }],
        output: { duplicate_facts: [0], contradicted_facts: [2] }
      })
    );
    expect(rfv?.newFact).toBe('Alice works at Acme');
    expect(rfv?.dupCount).toBe(1);
    expect(rfv?.contraCount).toBe(1);
    expect(rfv?.candidates.map((c) => [c.idx, c.origin, c.decision])).toEqual([
      [0, 'Existing fact', 'duplicate'],
      [1, 'Existing fact', 'none'],
      [2, 'Invalidation candidate', 'contradicted']
    ]);
  });

  it('returns null when the prompt has no NEW FACT block', () => {
    expect(resolveFactsView(stage({ input: [{ role: 'user', content: 'nope' }] }))).toBeNull();
  });
});

describe('prettyOutput / outputView', () => {
  it('pretty-prints the stage output as JSON', () => {
    expect(prettyOutput(stage({ output: { a: 1 } }))).toBe('{\n  "a": 1\n}');
  });

  it('outputView projects the stage output through toView', () => {
    expect(outputView(stage({ output: [{ a: 1 }] }))).toMatchObject({ kind: 'rows', columns: ['a'] });
    expect(outputView(stage({ output: null }))).toEqual({ kind: 'empty' });
  });
});

describe('briefName / briefType / dedupJson', () => {
  it('briefName/briefType fall back to dash / empty', () => {
    expect(briefName({ name: 'Bob' })).toBe('Bob');
    expect(briefName({})).toBe('—');
    expect(briefType({ entity_type: 'Person' })).toBe('Person');
    expect(briefType({})).toBe('');
  });

  it('dedupJson serializes the group input/output pairs', () => {
    const group = groupStages([
      stage({ node: 'dedup_entities_auto', input: { name: 'Bob' }, output: { merged_into: { name: 'Robert' } } })
    ])[0];
    expect(JSON.parse(dedupJson(group))).toEqual([
      { input: { name: 'Bob' }, output: { merged_into: { name: 'Robert' } } }
    ]);
  });
});

describe('dedupMerges', () => {
  it('maps each auto-merge stage to a from→into pair', () => {
    const group = groupStages([
      stage({
        node: 'dedup_entities_auto',
        source: 'dedup',
        input: { name: 'Bob', entity_type: 'Person' },
        output: { merged_into: { name: 'Robert', summary: 'kept' } }
      })
    ])[0];
    expect(dedupMerges(group)).toEqual([
      { idx: 0, from: { name: 'Bob', entity_type: 'Person' }, into: { name: 'Robert', summary: 'kept' } }
    ]);
  });
});

describe('extractedEntities', () => {
  const legend: IngestEntityType[] = [
    { id: 0, name: 'Entity', description: 'base' },
    { id: 1, name: 'Person', description: 'a human' }
  ];
  const map = buildEntityTypeMap(legend);

  it('resolves numeric type ids to names + descriptions', () => {
    const rows = extractedEntities(
      stage({ output: { extracted_entities: [{ name: 'Alice', entity_type_id: 1 }] } }),
      map
    );
    expect(rows).toEqual([{ name: 'Alice', typeName: 'Person', description: 'a human' }]);
  });

  it('falls back to #id when the legend lacks the id, and null for non-entity output', () => {
    const rows = extractedEntities(
      stage({ output: { extracted_entities: [{ name: 'X', entity_type_id: 9 }] } }),
      map
    );
    expect(rows?.[0]).toEqual({ name: 'X', typeName: '#9', description: '' });
    expect(extractedEntities(stage({ output: { other: 1 } }), map)).toBeNull();
  });
});

describe('stageMeta / stageCount', () => {
  const map = buildEntityTypeMap([{ id: 1, name: 'Person', description: '' }]);

  it('joins operation · model · tokens · elapsed', () => {
    expect(
      stageMeta(
        stage({ operation: 'add', model_id: 'gpt', input_tokens: 10, output_tokens: 5, elapsed_ms: 12.34 })
      )
    ).toBe('add · gpt · 10i/5o · 12.3ms');
  });

  it('counts entities, fact candidates, or table rows; null otherwise', () => {
    expect(
      stageCount(
        stage({ output: { extracted_entities: [{ name: 'a' }, { name: 'b' }] } }),
        'extract_entities',
        map
      )
    ).toBe(2);
    expect(stageCount(stage({ output: { a: 1 } }), 'summarize_entities', map)).toBeNull();
    expect(stageCount(stage({ output: [{ a: 1 }] }), 'extract_facts', map)).toBe(1);
  });
});
