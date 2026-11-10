/**
 * Hiro's own AI jobs (Phase 7b step 5): each job (chat, memory retrieval, knowledge answering, …)
 * points at ONE AI profile (`prefs.ai.profiles`) through its own preference field; an unset field
 * borrows the profile of the job it falls back to (chat-like jobs → chat; graph small steps → graph
 * extraction; …; chat and reading pictures fall back to nothing, i.e. off).
 *
 * Mirrors the backend's `domain/preferences/jobs.JOB_PRESETS` (id, field, label, falls_back_to) so
 * pages that only hold preferences (Settings, the Eval strip) can say what a job uses on the DRAFT.
 * `GET /api/ai/profiles` returns the same table as `jobs` (plus the model each runs with now); the
 * `hiro-jobs` test asserts the paths here are exactly the schema's `ai_profile_ref` fields. Pure.
 */
import type { AiProfile, VoiceProfile } from '$lib/api/generated/preferences.generated';
import type { PreferencePath } from '$lib/api/generated/preferences-paths.generated';

export type HiroJobId =
  | 'chat'
  | 'memory'
  | 'knowledge'
  | 'rewrite'
  | 'graph_extraction'
  | 'graph_small'
  | 'eval_answer'
  | 'eval_judge'
  | 'eval_retrieval'
  | 'vision';

export type HiroJob = {
  id: HiroJobId;
  /** The preference field holding the job's AI profile id (null = not set). */
  path: PreferencePath;
  label: string;
  /** The job whose profile an unset field borrows; null = nothing (the job is off). */
  fallsBackTo: HiroJobId | null;
};

export const HIRO_JOBS: readonly HiroJob[] = [
  { id: 'chat', path: 'llm.chat_profile', label: "Hiro's chat", fallsBackTo: null },
  { id: 'memory', path: 'memory.retrieval.profile', label: 'Memory retrieval', fallsBackTo: 'chat' },
  { id: 'knowledge', path: 'knowledge.answering.profile', label: 'Knowledge answering', fallsBackTo: 'chat' },
  {
    id: 'rewrite',
    path: 'knowledge.answering.rewrite_profile',
    label: 'Knowledge query rewrite',
    fallsBackTo: 'knowledge'
  },
  { id: 'graph_extraction', path: 'graph.extraction_profile', label: 'Graph extraction', fallsBackTo: 'chat' },
  { id: 'graph_small', path: 'graph.small_profile', label: 'Graph small steps', fallsBackTo: 'graph_extraction' },
  { id: 'eval_answer', path: 'graph.eval.answer_profile', label: 'Eval: answer', fallsBackTo: 'chat' },
  { id: 'eval_judge', path: 'graph.eval.judge_profile', label: 'Eval: judge', fallsBackTo: 'chat' },
  { id: 'eval_retrieval', path: 'graph.eval.retrieval_profile', label: 'Eval: retrieval', fallsBackTo: 'eval_answer' },
  { id: 'vision', path: 'llm.vision_profile', label: 'Reading pictures', fallsBackTo: null }
];

/** Hiro's own voice: the voice profile its voice replies use after the character's own. */
export const HIRO_VOICE_PATH: PreferencePath = 'voice.hiro_profile';

/** The plan-tool providers (Claude Code, Codex): a job may not point at their models. */
export const AI_PLAN_PROVIDERS: readonly string[] = ['claude_code', 'codex'];

export function isPlanModel(model: string | null | undefined): boolean {
  return AI_PLAN_PROVIDERS.includes((model ?? '').split(':')[0]);
}

export function hiroJob(id: HiroJobId): HiroJob {
  const job = HIRO_JOBS.find((j) => j.id === id);
  if (!job) throw new Error(`Unknown Hiro job ${id}`);
  return job;
}

export function hiroJobByPath(path: string): HiroJob | undefined {
  return HIRO_JOBS.find((j) => j.path === path);
}

/** Just the bits of preferences these helpers read (the draft or a saved payload). */
type PrefsWithProfiles = { ai: { profiles: Record<string, AiProfile> } };

function readPath(prefs: unknown, path: string): unknown {
  let node: unknown = prefs;
  for (const part of path.split('.')) {
    if (node === null || typeof node !== 'object') return undefined;
    node = (node as Record<string, unknown>)[part];
  }
  return node;
}

/** The AI profile id the job's own field holds (null when not set). */
export function jobProfileRef(prefs: unknown, id: HiroJobId): string | null {
  const value = readPath(prefs, hiroJob(id).path);
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

export type ResolvedJobProfile = {
  /** The job whose field supplied the profile (the job itself, or the one it borrows from). */
  from: HiroJob;
  profileId: string;
  /** Absent when the field names a profile that doesn't exist. */
  profile: AiProfile | undefined;
};

/** The profile a job runs with: its own field, else the field of the job it falls back to. */
export function resolveJobProfile(prefs: PrefsWithProfiles, id: HiroJobId): ResolvedJobProfile | null {
  const seen = new Set<HiroJobId>();
  let current: HiroJobId | null = id;
  while (current && !seen.has(current)) {
    seen.add(current);
    const ref = jobProfileRef(prefs, current);
    if (ref) return { from: hiroJob(current), profileId: ref, profile: prefs.ai.profiles?.[ref] };
    current = hiroJob(current).fallsBackTo;
  }
  return null;
}

/** Jobs whose own field points straight at the profile ("Chat, Eval: judge"). */
export function jobsUsingProfile(prefs: unknown, profileId: string): HiroJob[] {
  return HIRO_JOBS.filter((j) => jobProfileRef(prefs, j.id) === profileId);
}

/** How a model is named on a line: catalog display name and provider label when known. */
export type ModelNamer = (model: string) => { provider: string; model: string };

/** The plain id split ("google:gemini-x" → "google", "gemini-x"); the fallback namer. */
export const rawModelNamer: ModelNamer = (model) => {
  const i = model.indexOf(':');
  return i > 0 ? { provider: model.slice(0, i), model: model.slice(i + 1) } : { provider: '', model };
};

/** "Google · Gemini 3.8 Flash · temperature 0.3 · 2,048 tokens · thinking low". */
export function aiProfileLine(profile: AiProfile, namer: ModelNamer = rawModelNamer): string {
  const { provider, model } = namer(profile.model);
  const parts = [provider, model].filter(Boolean);
  if (profile.temperature != null) parts.push(`temperature ${profile.temperature}`);
  if (profile.max_tokens != null) parts.push(`${profile.max_tokens.toLocaleString('en-US')} tokens`);
  parts.push(profile.thinking ? `thinking ${profile.thinking}` : 'thinking: model default');
  return parts.join(' · ');
}

/** "Google · Gemini 3.8 Flash TTS · Kore · 1.1×". */
export function voiceProfileLine(profile: VoiceProfile, namer: ModelNamer = rawModelNamer): string {
  const { provider, model } = namer(profile.model);
  const parts = [provider, model, profile.voice_label || profile.voice].filter(Boolean);
  if (profile.speed && profile.speed !== 1) parts.push(`${profile.speed}×`);
  return parts.join(' · ');
}

/**
 * What an unset job field means, in words: "Not set: uses Graph extraction's profile (…)" or
 * "Not set: off." — computed on the given preferences (the draft on Settings).
 */
export function jobFallbackLine(prefs: PrefsWithProfiles, id: HiroJobId, namer: ModelNamer = rawModelNamer): string {
  const parent = hiroJob(id).fallsBackTo;
  if (!parent) return id === 'vision' ? "Not set: pictures aren't read." : 'Not set: off.';
  const resolved = resolveJobProfile(prefs, parent);
  const parentLabel = hiroJob(parent).label;
  if (!resolved) return `Not set: falls back to ${parentLabel}, which isn't set either (off).`;
  const name = resolved.profile?.label ?? resolved.profileId;
  const via = resolved.from.id === parent ? '' : ` (via ${resolved.from.label})`;
  const line = resolved.profile ? `: ${namer(resolved.profile.model).model}` : '';
  return `Not set: falls back to ${parentLabel} — ${name}${via}${line}.`;
}
