import { describe, expect, it } from 'vitest';
import type { AiProfile, AiProviderOption, AiUse } from './ai-types';
import {
  loadedWords,
  planAccountWords,
  planToolStatus,
  serverStatus,
  aiProvidersFromCatalog,
  catalogThinkingLevels,
  chainLabel,
  checkDraftFallback,
  fallbackChain,
  needsMismatch,
  profileIdFor,
  splitModelRef,
  temperatureNote,
  thinkingFor,
  usageLabel
} from './ai-profile-rules';

function profile(id: string, fallbackId: string | null = null): AiProfile {
  return {
    id,
    name: id.toUpperCase(),
    model: 'google:gemini-3.8-flash',
    thinking: 'low',
    temperature: null,
    maxTokens: null,
    context: null,
    instructions: '',
    budget: { costPerDay: 1, perHour: null, atOnce: 1 },
    fallbackId,
    usage: { todayAsks: 41, todayCost: 0.34, thisHour: 0 },
    preset: null,
    jobs: []
  };
}

const provider = (over: Partial<AiProviderOption> = {}): AiProviderOption => ({
  id: 'local-pc',
  label: 'PC',
  kind: 'local',
  models: [],
  temperatureIgnored: null,
  notReady: null,
  ...over
});

describe('splitModelRef', () => {
  it('splits at the first colon only', () => {
    expect(splitModelRef('pc-lm-studio:qwen3:8b')).toEqual({ providerId: 'pc-lm-studio', modelId: 'qwen3:8b' });
    expect(splitModelRef('bare')).toEqual({ providerId: '', modelId: 'bare' });
  });
});

describe('fallbackChain', () => {
  it('walks the chain in order', () => {
    const all = [profile('a', 'b'), profile('b', 'c'), profile('c')];
    expect(fallbackChain(all, 'a')).toEqual({ ids: ['b', 'c'], problem: null });
    expect(chainLabel(all, fallbackChain(all, 'a'))).toBe('→ B → C');
  });

  it('finds a loop', () => {
    const all = [profile('a', 'b'), profile('b', 'a')];
    expect(fallbackChain(all, 'a').problem).toBe('loop');
  });

  it('refuses more than 3 fallbacks', () => {
    const all = [profile('a', 'b'), profile('b', 'c'), profile('c', 'd'), profile('d', 'e'), profile('e')];
    expect(fallbackChain(all, 'b').problem).toBeNull();
    expect(fallbackChain(all, 'a').problem).toBe('too-long');
  });

  it('ends quietly at a missing profile', () => {
    expect(fallbackChain([profile('a', 'gone')], 'a')).toEqual({ ids: [], problem: null });
  });
});

describe('checkDraftFallback', () => {
  const saved = [profile('a', 'b'), profile('b'), profile('c', 'd'), profile('d')];

  it('accepts a fine chain', () => {
    expect(checkDraftFallback(saved, { ...profile('b'), fallbackId: 'c' }).message).toBeNull();
  });

  it('refuses a loop through the draft', () => {
    expect(checkDraftFallback(saved, { ...profile('b'), fallbackId: 'a' }).message).toMatch(/loop/);
  });

  it("refuses a change that makes another profile's chain too long", () => {
    // a → b → c → d → e would be 4 fallbacks for a, while b's own chain (3) is fine.
    const more = [...saved, profile('e')];
    const draft = { ...profile('d'), fallbackId: 'e' };
    const withB = more.map((p) => (p.id === 'b' ? { ...p, fallbackId: 'c' } : p));
    expect(checkDraftFallback(withB, draft).message).toMatch(/A's fallbacks run through/);
  });

  it('checks a new profile that is not in the list yet', () => {
    expect(checkDraftFallback(saved, { ...profile('new'), fallbackId: 'a' }).message).toBeNull();
  });
});

describe('notes', () => {
  it('says why temperature is off', () => {
    expect(temperatureNote(provider({ temperatureIgnored: 'Gemini ignores temperature.' }), 'low')).toBe(
      'Gemini ignores temperature.'
    );
    expect(temperatureNote(provider({ id: 'deepseek', kind: 'api' }), 'high')).toMatch(/thinking/);
    expect(temperatureNote(provider({ id: 'deepseek', kind: 'api' }), 'off')).toBeNull();
    expect(temperatureNote(provider(), 'off')).toBeNull();
  });

  it('keeps a supported thinking level, else the lowest', () => {
    const m = { ref: 'x:y', name: 'Y', thinking: ['low', 'high'] as const, pictures: true, sound: false };
    expect(thinkingFor({ ...m, thinking: [...m.thinking] }, 'high')).toBe('high');
    expect(thinkingFor({ ...m, thinking: [...m.thinking] }, 'off')).toBe('low');
    expect(thinkingFor(null, 'high')).toBeNull();
    expect(thinkingFor({ ...m, thinking: [...m.thinking] }, null)).toBeNull();
  });

  it('flags a use the model cannot serve', () => {
    const use: AiUse = { id: 'w', extension: 'Home', label: 'W', needs: { sound: true }, profileId: null };
    const m = { ref: 'x:y', name: 'Y', thinking: [], pictures: true, sound: false };
    expect(needsMismatch(use, provider(), m)).toMatch(/can't hear/);
    expect(needsMismatch(use, provider(), { ...m, sound: true })).toBeNull();
  });

  it('writes usage against the budget', () => {
    expect(usageLabel(profile('a'), 'api')).toBe('$0.34 of $1.00 today · 41 asks');
    const plan = { ...profile('a'), budget: { costPerDay: null, perHour: 10, atOnce: 1 }, usage: { todayAsks: 1, todayCost: 0, thisHour: 3 } };
    expect(usageLabel(plan, 'plan')).toBe('3 of 10 this hour · 1 ask today');
  });

  it('counts days and makes unique ids', () => {
    const now = new Date('2026-11-08T12:00:00Z');
    expect(profileIdFor('Camera questions', new Set(['camera-questions']))).toBe('camera-questions-2');
  });
});

describe('catalog rows → profile providers', () => {
  it('maps reasoning efforts to thinking levels', () => {
    const row = { id: 'x:y', provider_id: 'x', display_name: 'Y', model_kind: 'chat' };
    expect(catalogThinkingLevels({ ...row, reasoning_efforts: ['none', 'low', 'medium', 'high', 'xhigh', 'max'] })).toEqual([
      'off',
      'low',
      'medium',
      'high'
    ]);
    expect(catalogThinkingLevels({ ...row, reasoning_efforts: ['low', 'high'], thinking_off_type: 'disabled' })).toEqual([
      'off',
      'low',
      'high'
    ]);
    expect(catalogThinkingLevels(row)).toEqual(['off']);
  });

  it('groups rows by provider with kind, price and the temperature rule', () => {
    const providers = aiProvidersFromCatalog({
      models: [
        {
          id: 'google:g',
          provider_id: 'google',
          display_name: 'G',
          model_kind: 'chat',
          modalities: ['text', 'image_in', 'audio_in'],
          pricing: { input_per_1m_tokens: 0.75, output_per_1m_tokens: 3.75 }
        },
        { id: 'codex:c', provider_id: 'codex', display_name: 'C', model_kind: 'chat', hosting: 'plan' }
      ],
      providers: [{ id: 'google', display_name: 'Google', hosting: 'cloud' }],
      kindOf: (_id, hosting) => (hosting === 'plan' ? 'plan' : hosting === 'local' ? 'local' : 'api'),
      notReadyOf: () => null,
      temperatureIgnored: { google: 'Gemini ignores temperature.' }
    });
    expect(providers.map((p) => [p.id, p.kind, p.label])).toEqual([
      ['google', 'api', 'Google'],
      ['codex', 'plan', 'codex']
    ]);
    expect(providers[0].models[0]).toMatchObject({ pictures: true, sound: true, price: { input: 0.75, output: 3.75 } });
    expect(providers[0].temperatureIgnored).toMatch(/Gemini/);
    expect(providers[1].temperatureIgnored).toMatch(/sets its own/);
  });
});

describe('local-server and plan-tool rows', () => {
  const tool = {
    id: 'claude_code',
    name: 'Claude Code',
    installed: true,
    version: '2.4.1',
    signed_in: true,
    account: 'me@example.com',
    plan: 'Max',
    method: null,
    problem: null,
    signed_in_at: null,
    sign_in_ends_at: '2026-11-28T12:00:00Z',
    attention: true,
    takes_code: true,
    models: [],
    models_problem: null,
    sign_in: { state: 'none' as const, link: null, code: null, takes_code: true, code_sent: false, message: null },
    queue_note: ''
  };

  it('words a plan tool status', () => {
    expect(planToolStatus(tool)).toMatchObject({ tone: 'warn', word: 'expires soon' });
    expect(planToolStatus({ ...tool, attention: false }).word).toBe('signed in');
    expect(planToolStatus({ ...tool, signed_in: false }).word).toBe('signed out');
    expect(planToolStatus({ ...tool, installed: false }).word).toBe('not installed');
    expect(planAccountWords(tool)).toBe('Max plan · me@example.com');
  });

  it('words a local server status and what is loaded', () => {
    const server = {
      provider_id: 'ollama',
      base_url: 'http://127.0.0.1:11434',
      online: false,
      error: "Can't connect",
      models: [],
      state: 'down' as const,
      configured: true,
      checked_at: null,
      unload_idle_min: 60,
      context: 16384,
      batch: 2048
    };
    expect(serverStatus(server)).toMatchObject({ tone: 'warn', word: 'down' });
    expect(serverStatus({ ...server, state: 'no_address' }).word).toBe('no address');
    const model = { id: 'ollama:q', provider_id: 'ollama', name: 'q', display_name: 'Q', vision: true, reasoning: false, loaded: true, seen_at: '' };
    expect(loadedWords({ ...server, state: 'up', models: [{ ...model, loaded_by_core: true, idle_s: 180 }] })).toBe(
      'Q loaded by Hiro, idle 3 min'
    );
  });
});
