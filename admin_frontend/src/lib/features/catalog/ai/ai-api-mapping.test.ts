import { describe, expect, it } from 'vitest';
import type { AiProfileRow, AiTryPayload } from '$lib/api/ai';
import {
  localModelCatalogRows,
  planModelCatalogRows,
  profileFromRow,
  profileToPrefs,
  tryResultFrom,
  usesFromPayload
} from './ai-api-mapping';

const row: AiProfileRow = {
  id: 'camera-questions',
  label: 'Camera questions',
  model: 'google:gemini-3.8-flash',
  provider: 'google',
  provider_label: 'Google (Gemini)',
  kind: 'api',
  thinking: 'low',
  temperature: null,
  max_tokens: 1024,
  num_ctx: null,
  instructions: '',
  budget: { max_cost_day: 1, max_per_hour: null, at_once: 2 },
  budget_hint: '$1.00 a day',
  today: { asks: 41, cost: 0.34, this_hour: 4 },
  fallback: 'camera-on-codex',
  fallback_chain: ['camera-on-codex'],
  ready: true,
  not_ready: null
};

describe('profile mapping', () => {
  it('round-trips a profile row to the stored shape', () => {
    const profile = profileFromRow(row);
    expect(profile).toMatchObject({ name: 'Camera questions', fallbackId: 'camera-on-codex', usage: { todayAsks: 41 } });
    expect(profileToPrefs(profile)).toEqual({
      label: 'Camera questions',
      model: 'google:gemini-3.8-flash',
      thinking: 'low',
      temperature: null,
      max_tokens: 1024,
      num_ctx: null,
      instructions: '',
      max_cost_day: 1,
      max_per_hour: null,
      at_once: 2,
      fallback: 'camera-on-codex'
    });
  });

  it('turns empty or zero limits into no limit and trims instructions', () => {
    const profile = { ...profileFromRow(row), instructions: '  ', budget: { costPerDay: 0, perHour: 0, atOnce: 9 } };
    expect(profileToPrefs(profile)).toMatchObject({ instructions: '', max_cost_day: null, max_per_hour: null, at_once: 4 });
  });
});

describe('uses mapping', () => {
  it('groups uses per extension with new / removed marks', () => {
    const { groups, uses } = usesFromPayload([
      {
        extension: 'home',
        extension_id: 'ext1',
        connected: true,
        as_of: '2026-11-08T03:15:00Z',
        version: '1',
        uses: [
          { key: 'home:ask', id: 'ask', name: 'Ask a camera', pictures: 4, sound: false, json: true, profile_id: 'p', status: 'ok' },
          { key: 'home:door', id: 'door', name: 'Doorbell', pictures: 0, sound: true, json: true, profile_id: null, status: 'new' }
        ]
      }
    ]);
    expect(groups).toEqual([{ extension: 'home', extensionId: 'ext1', connected: true, asOf: '2026-11-08T03:15:00Z' }]);
    expect(uses[0]).toMatchObject({ id: 'home:ask', needs: { pictures: 4, json: true }, status: undefined });
    expect(uses[1]).toMatchObject({ needs: { sound: true }, status: 'new' });
  });
});

describe('local models and try it', () => {
  it('offers local models as catalog chat rows', () => {
    const [m] = localModelCatalogRows([
      { id: 'lm_studio:qwen', provider_id: 'lm_studio', name: 'qwen', display_name: 'Qwen', vision: true, reasoning: true, loaded: true, seen_at: '' }
    ]);
    expect(m).toMatchObject({ id: 'lm_studio:qwen', display_name: 'Qwen (loaded)', modalities: ['text', 'image_in'] });
  });

  it('offers the plan tools models with their own thinking levels', () => {
    const rows = planModelCatalogRows({
      id: 'codex',
      name: 'Codex',
      models: [
        { id: 'gpt-6.1-sol', name: 'GPT-6.1 Sol', about: '', thinking: ['low', 'high', 'xhigh'] },
        { id: 'x', name: 'X', about: '', thinking: [] }
      ]
    } as unknown as Parameters<typeof planModelCatalogRows>[0]);
    expect(rows[0]).toMatchObject({ id: 'codex:gpt-6.1-sol', provider_id: 'codex', ai_thinking: ['low', 'high'] });
    expect(rows[1].ai_thinking).toEqual([]);
  });

  it('words an answer and an error', () => {
    const ok: AiTryPayload = {
      ok: true,
      error: null,
      answer: {
        text: '{"answer":"yes"}',
        profile_id: 'p',
        profile_name: 'P',
        provider: 'google',
        model: 'gemini-3.8-flash',
        plan: false,
        ms: 1800,
        tokens: 100,
        tokens_in: 80,
        tokens_out: 20,
        cost: 0.0012,
        estimate: null,
        notes: [],
        tries: []
      }
    };
    expect(tryResultFrom(ok, 'api').result).toMatchObject({ seconds: 1.8, cost: 'about $0.0012' });
    const failed: AiTryPayload = { ok: false, answer: null, error: { code: 'budget', message: 'Over budget', notes: ['A: over'], tries: [] } };
    expect(tryResultFrom(failed, 'api').error).toBe('Over budget (A: over)');
  });
});
