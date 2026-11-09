/**
 * Phase 7b MOCKUP data (branch phase7b): what the core's pages look like once
 *  - every Hiro job (chat, memory, knowledge, graph, eval, reading pictures) points at an AI profile
 *    instead of a model + a tuning preset (today's 8 locked presets become default profiles), and
 *  - voices live in the core as voice recipes (provider, model, voice, style, speed), with Gemini's
 *    designed voices and the clip cache.
 * Nothing here is saved. The whole folder goes when 7b is built for real.
 */

// Off for the steps 2–4 deploy (2026-11-10): step 5's mockups (Hiro's jobs on AI profiles, characters' and Hiro's voices)
// would replace the real Preferences and character fields. Turn on to look at them again.
export const PHASE7B_MOCKUP = false;

// ── Default AI profiles for Hiro's jobs ─────────────────────────────────────────────────────────

export type MockProfile = {
  id: string;
  name: string;
  model: string;
  provider: string;
  kind: 'api' | 'plan' | 'local';
  thinking: string;
  temperature: number;
  maxTokens: number;
  budget: string;
  today: string;
  fallback: string; // names, "→"-joined; '' when none
  /** Was this locked tuning preset (converted once on the first start). */
  fromPreset: string;
};

export const MOCK_DEFAULT_PROFILES: MockProfile[] = [
  { id: 'job-chat', name: "Hiro's chat", model: 'Gemini 3.8 Flash', provider: 'Google', kind: 'api', thinking: 'Model default', temperature: 0.3, maxTokens: 2048, budget: 'up to $2.00 a day', today: '$0.41 of $2.00 today, 38 asks', fallback: 'Hiro\'s chat (Claude)', fromPreset: 'Balanced chat' },
  { id: 'job-chat-claude', name: "Hiro's chat (Claude)", model: 'Claude Sonnet 5.5', provider: 'Anthropic', kind: 'api', thinking: 'Model default', temperature: 0.3, maxTokens: 2048, budget: 'up to $1.00 a day', today: '$0.00 today', fallback: '', fromPreset: '' },
  { id: 'job-memory', name: 'Memory retrieval', model: 'Gemini 3.5 Flash Lite', provider: 'Google', kind: 'api', thinking: 'Low', temperature: 0, maxTokens: 8192, budget: 'no daily limit', today: '$0.06 today, 38 asks', fallback: '', fromPreset: 'Retrieval Agent Profile' },
  { id: 'job-knowledge', name: 'Knowledge answering', model: 'Claude Sonnet 5.5', provider: 'Anthropic', kind: 'api', thinking: 'Model default', temperature: 0.2, maxTokens: 1600, budget: 'no daily limit', today: '$0.12 today, 3 asks', fallback: '', fromPreset: 'Knowledge answering' },
  { id: 'job-rewrite', name: 'Knowledge query rewrite', model: 'Gemini 3.5 Flash Lite', provider: 'Google', kind: 'api', thinking: 'Off', temperature: 0, maxTokens: 1024, budget: 'no daily limit', today: '$0.00 today, 3 asks', fallback: '', fromPreset: 'Knowledge query rewrite' },
  { id: 'job-kg-extract', name: 'Knowledge graph extraction', model: 'GPT-6 Luna', provider: 'OpenAI', kind: 'api', thinking: 'Off', temperature: 0, maxTokens: 4096, budget: 'no daily limit', today: '$0.00 today', fallback: '', fromPreset: 'Knowledge graph extraction L3' },
  { id: 'job-kg-disamb', name: 'Knowledge graph disambiguation', model: 'GPT-6 Luna', provider: 'OpenAI', kind: 'api', thinking: 'Off', temperature: 0, maxTokens: 512, budget: 'no daily limit', today: '$0.00 today', fallback: '', fromPreset: 'Knowledge graph entity disambiguation L3' },
  { id: 'job-graph-extract', name: 'Graph extraction', model: 'GPT-6 Luna', provider: 'OpenAI', kind: 'api', thinking: 'Off', temperature: 0, maxTokens: 4096, budget: 'no daily limit', today: '$0.18 today, 24 asks', fallback: '', fromPreset: 'Graphiti extraction' },
  { id: 'job-graph-small', name: 'Graph small steps', model: 'GPT-6 Luna', provider: 'OpenAI', kind: 'api', thinking: 'Off', temperature: 0, maxTokens: 2048, budget: 'no daily limit', today: '$0.05 today, 61 asks', fallback: '', fromPreset: 'Graphiti small' },
  { id: 'job-vision', name: 'Reading pictures', model: 'Gemini 3.8 Flash', provider: 'Google', kind: 'api', thinking: 'Off', temperature: 0, maxTokens: 1024, budget: 'no daily limit', today: '$0.01 today, 2 asks', fallback: '', fromPreset: '' }
];

export type MockJob = {
  id: string;
  label: string;
  profileId: string;
  /** The preference that held this job's model before 7b (shown in the Preferences mock). */
  modelPath?: string;
  today: string; // what it used before 7b, in words
  needs?: string[];
};

/** Hiro's own jobs, each pointing at an AI profile (the Uses tab's "Hiro" group, and Preferences). */
export const MOCK_JOBS: MockJob[] = [
  { id: 'chat', label: 'Chat', profileId: 'job-chat', modelPath: 'llm.default_chat', today: 'Default chat model + Default chat model profile' },
  { id: 'memory', label: 'Memory retrieval', profileId: 'job-memory', modelPath: 'memory.retrieval.model', today: 'Memory → Retrieval model + its tuning preset' },
  { id: 'knowledge', label: 'Knowledge answering', profileId: 'job-knowledge', modelPath: 'knowledge.answering.model', today: 'Knowledge Answering Model + its tuning preset' },
  { id: 'rewrite', label: 'Knowledge query rewrite', profileId: 'job-rewrite', today: 'The answering model + the rewrite preset' },
  { id: 'kg-extract', label: 'Knowledge graph extraction', profileId: 'job-kg-extract', today: 'Its own locked preset' },
  { id: 'kg-disamb', label: 'Knowledge graph disambiguation', profileId: 'job-kg-disamb', today: 'Its own locked preset' },
  { id: 'graph-extract', label: 'Graph extraction', profileId: 'job-graph-extract', modelPath: 'graph.extraction_model', today: 'Graph Engine → Extraction model + preset' },
  { id: 'graph-small', label: 'Graph small steps', profileId: 'job-graph-small', modelPath: 'graph.small_model', today: 'Graph Engine → Small model + preset' },
  { id: 'vision', label: 'Reading pictures', profileId: 'job-vision', needs: ['a picture'], today: 'The IMAGE_VISION_MODEL environment variable' },
  { id: 'eval-answer', label: 'Eval: answer', profileId: 'job-knowledge', modelPath: 'graph.eval.answer_model', today: 'Eval → Answer model + preset' },
  { id: 'eval-judge', label: 'Eval: judge', profileId: 'job-chat-claude', modelPath: 'graph.eval.judge_model', today: 'Eval → Judge model + preset' },
  { id: 'eval-retrieval', label: 'Eval: retrieval', profileId: 'job-memory', modelPath: 'graph.eval.retrieval_model', today: 'Eval → Retrieval model + preset' }
];

export const jobByModelPath = (path: string) => MOCK_JOBS.find((j) => j.modelPath === path);
export const mockProfile = (id: string | undefined) => MOCK_DEFAULT_PROFILES.find((p) => p.id === id);
/** The jobs a default profile is set for ("Chat", "Eval: judge"). */
export const jobsUsing = (profileId: string) => MOCK_JOBS.filter((j) => j.profileId === profileId).map((j) => j.label);

export const profileLine = (p: MockProfile) =>
  `${p.provider} · ${p.model} · temperature ${p.temperature} · ${p.maxTokens.toLocaleString('en-US')} tokens · thinking ${p.thinking.toLowerCase()}`;

// ── Voices ──────────────────────────────────────────────────────────────────────────────────────

export type VoiceSource = 'studio' | 'library' | 'mine' | 'openai';

export type MockVoiceRecipe = {
  id: string;
  name: string;
  /** Catalog `provider:model` of a speech (tts) model. */
  modelId: string;
  provider: 'Google' | 'OpenAI';
  model: string;
  voice: string;
  voiceSource: VoiceSource;
  style: string;
  speed: number;
  usedBy: string[];
  today: string;
  /** A designed voice's id (`voice_…`) when it isn't in the list any more. */
  voiceId?: string;
  /** Gemini no longer has the designed voice (they expire after a year): the profile must pick another. */
  voiceGone?: boolean;
};

/** Voice profiles: the same idea as AI profiles (a named setup that uses point at), for speech. */
export const MOCK_VOICE_RECIPES: MockVoiceRecipe[] = [
  { id: 'v-hiro', name: "Hiro's voice", modelId: 'google:gemini-3.8-flash-tts', provider: 'Google', model: 'Gemini 3.8 Flash TTS', voice: 'Hiro', voiceSource: 'mine', style: 'Warm and calm, medium pace, a slight smile in the voice.', speed: 1, usedBy: ['Hiro: voice replies', 'Character: Hiro'], today: '41 clips, $0.09' },
  { id: 'v-door', name: 'Door alert', modelId: 'openai:gpt-4o-mini-tts', provider: 'OpenAI', model: 'gpt-4o-mini-tts', voice: 'sage', voiceSource: 'openai', style: 'Clear and friendly, a little brisk.', speed: 1.1, usedBy: ['Home: Speak (default)'], today: '12 clips, $0.01' },
  { id: 'v-bedtime', name: 'Bedtime story', modelId: 'google:gemini-3.8-flash-lite-tts', provider: 'Google', model: 'Gemini 3.8 Flash Lite TTS', voice: 'Kore', voiceSource: 'studio', style: 'Soft and slow, like reading to a child at night.', speed: 1, usedBy: ['Home: Speak node "Bedtime"'], today: 'none' },
  { id: 'v-arabic', name: 'Arabic news', modelId: 'google:gemini-3.8-flash-tts', provider: 'Google', model: 'Gemini 3.8 Flash TTS', voice: 'ar-EG-news-02', voiceSource: 'library', style: 'Neutral newsreader, Egyptian Arabic.', speed: 1, usedBy: ['Character: Layla'], today: '3 clips, $0.01' },
  { id: 'v-story', name: 'Story time', modelId: 'google:gemini-3.8-flash-tts', provider: 'Google', model: 'Gemini 3.8 Flash TTS', voice: 'Uncle Sami', voiceId: 'voice_77aa01', voiceSource: 'mine', voiceGone: true, style: 'Playful, with funny voices for each character.', speed: 1, usedBy: ['Home: Speak node "Story"'], today: 'none' },
  { id: 'v-announcer', name: 'Old announcer', modelId: 'openai:tts-1', provider: 'OpenAI', model: 'tts-1', voice: 'onyx', voiceSource: 'openai', style: '', speed: 1, usedBy: [], today: 'none' }
];

export const VOICE_SOURCE_LABEL: Record<VoiceSource, string> = {
  studio: 'Studio voice',
  library: 'Voice library',
  mine: 'Designed voice',
  openai: 'OpenAI voice'
};

/** Voice uses: what speaks, and the recipe each speaks with (the Uses tab). */
export const MOCK_VOICE_USES = [
  { group: 'Hiro', label: 'Voice replies', recipeId: 'v-hiro', note: 'A character with its own voices speaks with those first.' },
  { group: 'Home', label: 'Speak', recipeId: 'v-door', note: 'Alerts and the Speak node; a node can pick its own recipe in Home.' }
];

export const mockRecipe = (id: string | undefined) => MOCK_VOICE_RECIPES.find((r) => r.id === id);
export const recipeLine = (r: MockVoiceRecipe) =>
  `${r.provider} · ${r.model} · ${r.voice}${r.speed !== 1 ? ` · ${r.speed}×` : ''}`;

// ── A default profile as the real AI profile editor takes it (Edit opens it; Save is disabled) ──

import type { AiProfile } from '$lib/features/catalog/ai/ai-types';

const MODEL_IDS: Record<string, string> = {
  'Gemini 3.8 Flash': 'google:gemini-3.8-flash',
  'Gemini 3.5 Flash Lite': 'google:gemini-3.5-flash-lite',
  'Claude Sonnet 5.5': 'anthropic:claude-sonnet-5-5',
  'GPT-6 Luna': 'openai:gpt-6-luna'
};
const THINKING: Record<string, AiProfile['thinking']> = { 'Model default': null, Low: 'low', Off: 'off' };

export function toAiProfile(p: MockProfile): AiProfile {
  const perDay = /\$(\d+(?:\.\d+)?)/.exec(p.budget);
  const fallback = MOCK_DEFAULT_PROFILES.find((x) => x.name === p.fallback);
  return {
    id: p.id,
    name: p.name,
    model: MODEL_IDS[p.model] ?? '',
    thinking: THINKING[p.thinking] ?? null,
    temperature: p.temperature,
    maxTokens: p.maxTokens,
    context: null,
    instructions: '',
    budget: { costPerDay: perDay ? Number(perDay[1]) : null, perHour: null, atOnce: 1 },
    fallbackId: fallback?.id ?? null,
    usage: { todayAsks: 0, todayCost: 0, thisHour: 0 }
  };
}
