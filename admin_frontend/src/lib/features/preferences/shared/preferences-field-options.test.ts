import { describe, expect, it } from 'vitest';
import {
  assertPrefSelectOptionsMatchEnum,
  normalizePrefSelectOptions
} from './preferences-field-options';
import type { PreferenceFieldMeta } from '$lib/api/preferences-schema';

describe('preferences-field-options', () => {
  it('normalizes record options to an array', () => {
    expect(normalizePrefSelectOptions({ off: 'Off', graphiti: 'Graphiti' })).toEqual([
      { value: 'off', label: 'Off' },
      { value: 'graphiti', label: 'Graphiti' }
    ]);
  });

  it('asserts select options cover the schema enum domain', () => {
    const meta: PreferenceFieldMeta = {
      path: 'graph.backend',
      type: 'string',
      enum: ['off', 'graphiti']
    };
    expect(() =>
      assertPrefSelectOptionsMatchEnum(meta, [{ value: 'off', label: 'Off' }])
    ).toThrow(/Missing select label/);
    expect(() =>
      assertPrefSelectOptionsMatchEnum(meta, [
        { value: 'off', label: 'Off' },
        { value: 'graphiti', label: 'Graphiti' },
        { value: 'other', label: 'Other' }
      ])
    ).toThrow(/not in schema enum/);
  });
});
