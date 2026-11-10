import { describe, expect, it } from 'vitest';
import type { AiProfile } from '$lib/api/generated/preferences.generated';
import { PREFERENCES_FIELD_SCHEMA } from '$lib/api/preferences-field-schema';
import { PREFERENCE_TAB_REGISTRY } from '$lib/features/preferences/shared/preferences-tabs';
import type { PrefFieldSpec } from '$lib/features/preferences/widgets/manifest/manifest-types';
import {
  aiProfileLine,
  HIRO_JOBS,
  HIRO_VOICE_PATH,
  isPlanModel,
  jobFallbackLine,
  jobsUsingProfile,
  resolveJobProfile,
  voiceProfileLine
} from './hiro-jobs';

const profile = (label: string, model: string, extra: Partial<AiProfile> = {}): AiProfile => ({
  label,
  model,
  thinking: null,
  temperature: 0.3,
  max_tokens: 2048,
  num_ctx: null,
  instructions: '',
  max_cost_day: null,
  max_per_hour: null,
  at_once: 1,
  fallback: null,
  preset: null,
  ...extra
});

function prefs(fields: Record<string, string | null> = {}) {
  const p = {
    llm: { chat_profile: 'chat' as string | null, vision_profile: null as string | null },
    memory: { retrieval: { profile: null as string | null } },
    knowledge: { answering: { profile: null as string | null, rewrite_profile: null as string | null } },
    graph: {
      extraction_profile: 'extract' as string | null,
      small_profile: null as string | null,
      eval: { answer_profile: null, judge_profile: null, retrieval_profile: null } as Record<string, string | null>
    },
    ai: {
      profiles: {
        chat: profile("Hiro's chat", 'google:gemini-flash', { preset: 'chat' }),
        extract: profile('Graph extraction', 'openai:gpt-mini', { temperature: 0, thinking: 'off' })
      } as Record<string, AiProfile>
    }
  };
  for (const [path, value] of Object.entries(fields)) {
    const parts = path.split('.');
    let node: Record<string, unknown> = p as unknown as Record<string, unknown>;
    for (const part of parts.slice(0, -1)) node = node[part] as Record<string, unknown>;
    node[parts[parts.length - 1]] = value;
  }
  return p;
}

function specsOf(kind: PrefFieldSpec['kind']): string[] {
  const out: string[] = [];
  const walk = (spec: PrefFieldSpec) => {
    if (spec.kind === kind && 'path' in spec) out.push(spec.path);
    if ('fields' in spec) spec.fields.forEach(walk);
  };
  for (const tab of PREFERENCE_TAB_REGISTRY) for (const card of tab.manifest.cards) card.body.forEach(walk);
  return out;
}

const schemaPaths = (marker: 'ai_profile_ref' | 'voice_profile_ref') =>
  Object.values(PREFERENCES_FIELD_SCHEMA)
    .filter((m) => m[marker])
    .map((m) => m.path)
    .sort();

describe("Hiro's jobs (Phase 7b step 5)", () => {
  it("lists exactly the schema's AI-profile fields, and Hiro's voice is its voice-profile field", () => {
    expect(HIRO_JOBS.map((j) => j.path).sort()).toEqual(schemaPaths('ai_profile_ref'));
    expect(schemaPaths('voice_profile_ref')).toEqual([HIRO_VOICE_PATH]);
  });

  it('every profile field renders as a profile select on the Settings page (no model+tuning pair left)', () => {
    expect(specsOf('aiProfile').sort()).toEqual(schemaPaths('ai_profile_ref'));
    expect(specsOf('voiceProfile')).toEqual([HIRO_VOICE_PATH]);
  });

  it('every fallback names another job, and no chain loops', () => {
    const ids = new Set(HIRO_JOBS.map((j) => j.id));
    for (const job of HIRO_JOBS) {
      if (job.fallsBackTo) expect(ids.has(job.fallsBackTo), job.id).toBe(true);
      const seen = new Set<string>();
      let cur: string | null = job.id;
      while (cur) {
        expect(seen.has(cur), job.id).toBe(false);
        seen.add(cur);
        cur = HIRO_JOBS.find((j) => j.id === cur)?.fallsBackTo ?? null;
      }
    }
  });

  it("resolves a job to its own profile, else the job it falls back to (as the server's job_model_source)", () => {
    const p = prefs();
    expect(resolveJobProfile(p, 'chat')?.profileId).toBe('chat');
    expect(resolveJobProfile(p, 'graph_small')).toMatchObject({ profileId: 'extract', from: { id: 'graph_extraction' } });
    // rewrite → knowledge (unset) → chat
    expect(resolveJobProfile(p, 'rewrite')).toMatchObject({ profileId: 'chat', from: { id: 'chat' } });
    // vision has nothing to fall back to
    expect(resolveJobProfile(p, 'vision')).toBeNull();
    // a missing profile id still resolves (the profile is absent)
    expect(resolveJobProfile(prefs({ 'graph.extraction_profile': 'gone' }), 'graph_small')?.profile).toBeUndefined();
  });

  it('says what an unset job falls back to, on the given preferences', () => {
    expect(jobFallbackLine(prefs(), 'graph_small')).toBe('Not set: falls back to Graph extraction — Graph extraction: gpt-mini.');
    expect(jobFallbackLine(prefs(), 'rewrite')).toBe(
      "Not set: falls back to Knowledge answering — Hiro's chat (via Hiro's chat): gemini-flash."
    );
    expect(jobFallbackLine(prefs({ 'llm.chat_profile': null }), 'memory')).toBe(
      "Not set: falls back to Hiro's chat, which isn't set either (off)."
    );
    expect(jobFallbackLine(prefs(), 'vision')).toBe("Not set: pictures aren't read.");
    expect(jobFallbackLine(prefs(), 'chat')).toBe('Not set: off.');
  });

  it('lists the jobs pointing straight at a profile', () => {
    const p = prefs({ 'graph.eval.judge_profile': 'chat' });
    expect(jobsUsingProfile(p, 'chat').map((j) => j.label)).toEqual(["Hiro's chat", 'Eval: judge']);
    expect(jobsUsingProfile(p, 'extract').map((j) => j.id)).toEqual(['graph_extraction']);
  });

  it('flags plan-tool models (a job may not use them)', () => {
    expect(isPlanModel('claude_code:sonnet')).toBe(true);
    expect(isPlanModel('codex:gpt-5')).toBe(true);
    expect(isPlanModel('anthropic:claude-sonnet')).toBe(false);
    expect(isPlanModel(null)).toBe(false);
  });

  it('describes a profile in one line', () => {
    expect(aiProfileLine(profile('X', 'google:gemini-flash', { thinking: 'low' }))).toBe(
      'google · gemini-flash · temperature 0.3 · 2,048 tokens · thinking low'
    );
    expect(
      aiProfileLine(profile('X', 'openai:gpt', { temperature: null, max_tokens: null }), () => ({
        provider: 'OpenAI',
        model: 'GPT'
      }))
    ).toBe('OpenAI · GPT · thinking: model default');
    expect(
      voiceProfileLine({ label: 'V', model: 'openai:tts-1', voice: 'sage', voice_label: '', style: '', speed: 1.1 })
    ).toBe('openai · tts-1 · sage · 1.1×');
  });
});
