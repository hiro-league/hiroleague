import { describe, expect, it } from 'vitest';
import {
  coercePreferenceLeafValue,
  shouldSkipPreferencePath,
  shouldWriteWholePreferencePath
} from './preferences-edits-policy';
import type { PreferenceFieldMeta } from '$lib/api/preferences-schema';

describe('preferences-edits-policy', () => {
  it('skips read-only and preferences-save-skip paths', () => {
    expect(shouldSkipPreferencePath({ path: 'version', readOnly: true })).toBe(true);
    expect(
      shouldSkipPreferencePath({ path: 'image_profiles', preferencesSaveSkip: true })
    ).toBe(true);
    expect(shouldSkipPreferencePath({ path: 'memory.user_name', type: 'string' })).toBe(false);
  });

  it('detects whole-object writes', () => {
    expect(shouldWriteWholePreferencePath({ path: 'tuning_profiles', writeWhole: true })).toBe(
      true
    );
    expect(shouldWriteWholePreferencePath({ path: 'memory.user_name', type: 'string' })).toBe(
      false
    );
  });

  it('coerces nullable model and string leaves', () => {
    const modelMeta: PreferenceFieldMeta = {
      path: 'llm.default_chat',
      nullable: true,
      model_kind: 'chat',
      type: 'string'
    };
    expect(coercePreferenceLeafValue(modelMeta, '')).toBeNull();
    expect(coercePreferenceLeafValue(modelMeta, 'openai:gpt-4')).toBe('openai:gpt-4');

    const deviceMeta: PreferenceFieldMeta = {
      path: 'graph.reranker.device',
      nullable: true,
      type: 'string'
    };
    expect(coercePreferenceLeafValue(deviceMeta, '  ')).toBeNull();
  });
});
