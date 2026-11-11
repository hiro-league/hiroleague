import { describe, expect, it } from 'vitest';
import type { CharacterResolvedPayload } from '$lib/api/characters';
import {
  appliedTuningLine,
  llmCollapsedSummary,
  resolvedRowDotTone,
  resolvedRowTooltip,
  voiceCollapsedSummary
} from '$lib/features/characters/shared/characters-resolved-pure';

function basePayload(over: Partial<CharacterResolvedPayload> = {}): CharacterResolvedPayload {
  return {
    character_id: 'c1',
    ai_rows: [],
    ai_workspace_row: null,
    ai_applied: null,
    voice_rows: [],
    voice_workspace_row: null,
    voice_applied: null,
    voice_disabled: false,
    ...over
  };
}

const applied = (over: Partial<NonNullable<CharacterResolvedPayload['ai_applied']>> = {}) => ({
  source: 'character' as const,
  profile_id: 'hiro-chat',
  profile_label: "Hiro's chat",
  model_id: 'google:gemini-flash',
  temperature: 0.3,
  max_tokens: 2048,
  thinking: null,
  num_ctx: null,
  ...over
});

describe('llmCollapsedSummary', () => {
  it('returns placeholder when nothing applied', () => {
    expect(llmCollapsedSummary(basePayload())).toBe('No model resolved');
  });

  it('names the profile that answers and its model', () => {
    expect(llmCollapsedSummary(basePayload({ ai_applied: applied() }))).toBe("Hiro's chat · google:gemini-flash");
  });

  it('returns just the model when the profile has no name', () => {
    expect(llmCollapsedSummary(basePayload({ ai_applied: applied({ profile_label: null }) }))).toBe(
      'google:gemini-flash'
    );
  });
});

describe('appliedTuningLine', () => {
  it('lists temperature, max tokens and thinking (+ context when set)', () => {
    expect(appliedTuningLine(applied())).toBe('temp 0.3 · max tokens 2,048 · thinking: model default');
    expect(appliedTuningLine(applied({ thinking: 'low', num_ctx: 8192 }))).toBe(
      'temp 0.3 · max tokens 2,048 · thinking low · context 8,192'
    );
  });
});

describe('voiceCollapsedSummary', () => {
  it('reports disabled voice first, before checking applied', () => {
    expect(voiceCollapsedSummary(basePayload({ voice_disabled: true }))).toBe('Voice replies disabled');
  });

  it('returns placeholder when no voice applied', () => {
    expect(voiceCollapsedSummary(basePayload())).toBe('No voice resolved');
  });

  it('combines the profile name, model and voice', () => {
    const payload = basePayload({
      voice_applied: {
        source: 'hiro',
        profile_id: 'hiro-voice',
        label: "Hiro's voice",
        model: 'openai:gpt-4o-mini-tts',
        voice: 'sage',
        style: ''
      }
    });
    expect(voiceCollapsedSummary(payload)).toBe("Hiro's voice · openai:gpt-4o-mini-tts · sage");
  });
});

describe('resolvedRowTooltip', () => {
  it('maps every AI and voice row status to a non-empty hint', () => {
    for (const status of ['available', 'unavailable', 'plan', 'missing', 'no_key'] as const) {
      expect(resolvedRowTooltip(status).length).toBeGreaterThan(0);
    }
  });
});

describe('resolvedRowDotTone', () => {
  it('colors usable, skipped and plan-tool rows distinctly', () => {
    expect(resolvedRowDotTone('available')).toBe('ok');
    expect(resolvedRowDotTone('unavailable')).toBe('error');
    expect(resolvedRowDotTone('no_key')).toBe('error');
    expect(resolvedRowDotTone('missing')).toBe('error');
    expect(resolvedRowDotTone('plan')).toBe('warn');
  });
});
