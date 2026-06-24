import { describe, expect, it } from 'vitest';
import {
  preferenceFieldMeta,
  preferenceHint,
  preferenceNumberBounds
} from './preferences-schema';
import type { PreferencesSchemaMap } from './preferences-schema';

const FIXTURE: PreferencesSchemaMap = {
  'knowledge.chunking.chunk_size': {
    path: 'knowledge.chunking.chunk_size',
    type: 'integer',
    min: 200,
    max: 8000,
    description: 'Target size per chunk.'
  }
};

describe('preferences-schema helpers', () => {
  it('looks up field meta by dotted path', () => {
    expect(preferenceFieldMeta(FIXTURE, 'knowledge.chunking.chunk_size')?.min).toBe(200);
    expect(preferenceFieldMeta(FIXTURE, 'missing')).toBeNull();
  });

  it('maps number bounds and hints from meta', () => {
    const meta = preferenceFieldMeta(FIXTURE, 'knowledge.chunking.chunk_size');
    expect(preferenceNumberBounds(meta)).toEqual({ min: 200, max: 8000, step: undefined });
    expect(preferenceHint(meta)).toBe('Target size per chunk.');
  });
});
