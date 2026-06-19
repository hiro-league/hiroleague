import { describe, expect, it } from 'vitest';
import type { CharacterResolvedPayload, CharacterResolvedRow } from '$lib/api/characters';
import {
  llmCollapsedSummary,
  resolvedRowDotClass,
  resolvedRowTooltip,
  voiceCollapsedSummary
} from '$lib/features/characters/shared/characters-resolved-pure';

function basePayload(over: Partial<CharacterResolvedPayload> = {}): CharacterResolvedPayload {
  return {
    character_id: 'c1',
    llm_rows: [],
    llm_workspace_row: null,
    llm_applied: null,
    voice_rows: [],
    voice_workspace_row: null,
    voice_applied: null,
    voice_disabled: false,
    ...over
  };
}

function row(over: Partial<CharacterResolvedRow> = {}): CharacterResolvedRow {
  return { model_id: 'm1', status: 'available', ...over };
}

describe('llmCollapsedSummary', () => {
  it('returns placeholder when nothing applied', () => {
    expect(llmCollapsedSummary(basePayload())).toBe('No model resolved');
  });

  it('appends display name from the matching character row', () => {
    const payload = basePayload({
      llm_rows: [row({ model_id: 'gpt-x', display_name: 'GPT X' })],
      llm_applied: { source: 'character', model_id: 'gpt-x', temperature: 0.5, max_tokens: 100 }
    });
    expect(llmCollapsedSummary(payload)).toBe('gpt-x · GPT X');
  });

  it('falls back to the workspace row for the display name', () => {
    const payload = basePayload({
      llm_workspace_row: row({ model_id: 'ws', display_name: 'Workspace Model' }),
      llm_applied: { source: 'workspace_fallback', model_id: 'ws', temperature: 0.5, max_tokens: 100 }
    });
    expect(llmCollapsedSummary(payload)).toBe('ws · Workspace Model');
  });

  it('returns just the id when no display name is found', () => {
    const payload = basePayload({
      llm_applied: { source: 'character', model_id: 'bare', temperature: 0.5, max_tokens: 100 }
    });
    expect(llmCollapsedSummary(payload)).toBe('bare');
  });
});

describe('voiceCollapsedSummary', () => {
  it('reports disabled voice first, before checking applied', () => {
    expect(voiceCollapsedSummary(basePayload({ voice_disabled: true }))).toBe(
      'Voice replies disabled'
    );
  });

  it('returns placeholder when no TTS model applied', () => {
    expect(voiceCollapsedSummary(basePayload())).toBe('No TTS model resolved');
  });

  it('combines id, display name and voice', () => {
    const payload = basePayload({
      voice_rows: [row({ model_id: 'tts-1', display_name: 'Nice TTS' })],
      voice_applied: {
        source: 'character',
        catalog_model_id: 'tts-1',
        synthesis: { model: 'tts-1', voice: 'alloy', instructions: '' }
      }
    });
    expect(voiceCollapsedSummary(payload)).toBe('tts-1 · Nice TTS · alloy');
  });

  it('omits the voice segment when no voice is set', () => {
    const payload = basePayload({
      voice_applied: {
        source: 'workspace_fallback',
        catalog_model_id: 'tts-2',
        synthesis: { model: 'tts-2', voice: '', instructions: '' }
      }
    });
    expect(voiceCollapsedSummary(payload)).toBe('tts-2');
  });
});

describe('resolvedRowTooltip', () => {
  it('maps every status to a non-empty hint', () => {
    for (const status of [
      'available',
      'unavailable',
      'unknown',
      'wrong_kind',
      'deprecated'
    ] as const) {
      expect(resolvedRowTooltip(status).length).toBeGreaterThan(0);
    }
  });
});

describe('resolvedRowDotClass', () => {
  it('colors usable, broken and deprecated states distinctly', () => {
    expect(resolvedRowDotClass('available')).toBe('bg-emerald-500');
    expect(resolvedRowDotClass('unavailable')).toBe('bg-red-500');
    expect(resolvedRowDotClass('wrong_kind')).toBe('bg-red-500');
    expect(resolvedRowDotClass('deprecated')).toBe('bg-amber-500');
    expect(resolvedRowDotClass('unknown')).toBe('bg-muted-foreground/50');
  });
});
