import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  boolCodec,
  enumCodec,
  intCodec,
  jsonBoolField,
  jsonRecordCodec,
  jsonStringField
} from './codecs';
import { decodeGraphOptionsRaw, encodeGraphOptions, GRAPH_OPTION_DEFAULTS } from '$lib/features/knowledge/graph/knowledge-graph-prefs';

describe('enumCodec', () => {
  it('round-trips allowed members and falls back on garbage', () => {
    const codec = enumCodec(['a', 'b'] as const, 'a');
    expect(codec.decode('b')).toBe('b');
    expect(codec.decode('nope')).toBe('a');
    expect(codec.decode(null)).toBe('a');
    expect(codec.encode('b')).toBe('b');
  });
});

describe('intCodec', () => {
  it('clamps and round-trips boundary values', () => {
    const codec = intCodec({ min: 0, max: 10, default: 5 });
    expect(codec.decode('99')).toBe(10);
    expect(codec.decode('-1')).toBe(0);
    expect(codec.decode('abc')).toBe(5);
    expect(codec.encode(7)).toBe('7');
  });
});

describe('boolCodec', () => {
  it('supports bool and bool01 encodings', () => {
    expect(boolCodec(false).decode('true')).toBe(true);
    expect(boolCodec(true, 'bool01').decode('0')).toBe(false);
    expect(boolCodec(true, 'bool01').encode(true)).toBe('1');
  });
});

describe('jsonRecordCodec', () => {
  type Row = { name: string; on: boolean };

  const codec = jsonRecordCodec(
    {
      name: jsonStringField(''),
      on: jsonBoolField(false)
    },
    { name: '', on: false }
  );

  it('keeps valid fields when one field is corrupt', () => {
    const raw = JSON.stringify({ name: 'alpha', on: 'not-bool' });
    expect(codec.decode(raw)).toEqual({ name: 'alpha', on: false });
  });

  it('returns defaults for non-JSON without throwing', () => {
    expect(codec.decode('{bad')).toEqual({ name: '', on: false });
  });

  it('round-trips', () => {
    const value = { name: 'beta', on: true };
    expect(codec.decode(codec.encode(value)!)).toEqual(value);
  });
});

describe('graph options codec payload', () => {
  it('matches legacy encodeGraphOptions output', () => {
    const sample = { ...GRAPH_OPTION_DEFAULTS, linkStrength: 0.75, searchFocusMode: 'dim' as const };
    const encoded = encodeGraphOptions(sample);
    expect(decodeGraphOptionsRaw(encoded)).toEqual(decodeGraphOptionsRaw(JSON.stringify(sample)));
  });
});
