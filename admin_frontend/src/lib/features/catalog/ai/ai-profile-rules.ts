/**
 * Pure rules for AI profiles: model lookup, fallback chains (no loops, at most 3), budgets, and the
 * plain-words notes the pages show. No Svelte, no I/O — shared by the controller and the views.
 */
import type { LocalServerStatus, PlanToolStatus, PlanUpdates } from '$lib/api/ai';
import type { CatalogProviderRow } from '$lib/api/catalog';
import { humanDateTime } from '$lib/format/human-datetime';
import type {
  AiCatalogModelRow,
  AiModelOption,
  AiProfile,
  AiProviderKind,
  AiProviderOption,
  AiThinking,
  AiUse,
  ProviderRowStatus
} from './ai-types';

/** Catalog hosting kind of the plan-tool providers (`claude_code`, `codex`). */
export const PLAN_HOSTING = 'plan';

/** The local server kinds (catalog providers hosted `local` the core loads models on). */
export const LOCAL_SERVER_IDS = ['lm_studio', 'ollama'] as const;

/** Longest fallback chain: a profile may hand off to at most this many others in a row. */
export const MAX_FALLBACKS = 3;

export const AT_ONCE_OPTIONS = [1, 2, 3, 4] as const;

export const THINKING_LABELS: Record<AiThinking, string> = {
  off: 'Off',
  minimal: 'Minimal',
  low: 'Low',
  medium: 'Medium',
  high: 'High'
};

/** Thinking level in words; null = the model's default. */
export function thinkingWords(thinking: AiThinking | null): string {
  return thinking ? THINKING_LABELS[thinking] : 'Model default';
}

/** Providers whose API ignores temperature (from catalog.yaml notes). */
export const TEMPERATURE_IGNORED: Record<string, string> = {
  google: 'Gemini ignores temperature.',
  openai: 'GPT-6 models take no temperature.',
  anthropic: 'Claude models take no temperature.'
};

export const PROVIDER_KIND_LABELS: Record<AiProviderKind, string> = {
  api: 'API',
  local: 'Local',
  plan: 'Plan'
};

export const LOCAL_SERVER_KIND_LABELS: Record<string, string> = {
  lm_studio: 'LM Studio',
  ollama: 'Ollama'
};

/** `provider:model` → its parts (split at the FIRST colon; model ids may hold more colons). */
export function splitModelRef(ref: string): { providerId: string; modelId: string } {
  const i = ref.indexOf(':');
  return i === -1 ? { providerId: '', modelId: ref } : { providerId: ref.slice(0, i), modelId: ref.slice(i + 1) };
}

export function findModel(
  providers: readonly AiProviderOption[],
  ref: string
): { provider: AiProviderOption | null; model: AiModelOption | null } {
  const { providerId } = splitModelRef(ref);
  const provider = providers.find((p) => p.id === providerId) ?? null;
  return { provider, model: provider?.models.find((m) => m.ref === ref) ?? null };
}

export type FallbackProblem = 'loop' | 'too-long';

export type FallbackChain = {
  /** Profile ids after the start, in order (stops before a repeat). */
  ids: string[];
  problem: FallbackProblem | null;
};

/** Walk `startId`'s fallbacks. A missing fallback id ends the chain quietly. */
export function fallbackChain(profiles: readonly AiProfile[], startId: string): FallbackChain {
  const byId = new Map(profiles.map((p) => [p.id, p]));
  const seen = new Set([startId]);
  const ids: string[] = [];
  let next = byId.get(startId)?.fallbackId ?? null;
  while (next && byId.has(next)) {
    if (seen.has(next)) return { ids, problem: 'loop' };
    seen.add(next);
    ids.push(next);
    if (ids.length > MAX_FALLBACKS) return { ids, problem: 'too-long' };
    next = byId.get(next)?.fallbackId ?? null;
  }
  return { ids, problem: null };
}

/** Profiles with `draft` in place of its saved copy (or added, when new). */
export function withDraft(profiles: readonly AiProfile[], draft: AiProfile): AiProfile[] {
  return profiles.some((p) => p.id === draft.id)
    ? profiles.map((p) => (p.id === draft.id ? draft : p))
    : [...profiles, draft];
}

/**
 * Check a profile being edited: its own chain, and every other chain that runs through it (pointing
 * this profile somewhere new can make another profile's chain too long). Null message = fine.
 */
export function checkDraftFallback(
  profiles: readonly AiProfile[],
  draft: AiProfile
): { chain: FallbackChain; message: string | null } {
  const all = withDraft(profiles, draft);
  const nameOf = (id: string) => all.find((p) => p.id === id)?.name || 'this profile';
  const chain = fallbackChain(all, draft.id);
  if (chain.problem === 'loop') {
    return { chain, message: `That makes a loop: the chain comes back to ${nameOf(draft.id)}. Pick another fallback.` };
  }
  if (chain.problem === 'too-long') {
    return { chain, message: `Too long: at most ${MAX_FALLBACKS} fallbacks in a row.` };
  }
  for (const other of all) {
    if (other.id === draft.id) continue;
    const theirs = fallbackChain(all, other.id);
    if (theirs.problem && (theirs.ids.includes(draft.id) || other.fallbackId === draft.id)) {
      const why = theirs.problem === 'loop' ? 'a loop' : `more than ${MAX_FALLBACKS} fallbacks`;
      return { chain, message: `${other.name}'s fallbacks run through this profile: this would give it ${why}.` };
    }
  }
  return { chain, message: null };
}

/** "→ Camera on Codex → Local vision", or "" when there is no fallback. */
export function chainLabel(profiles: readonly AiProfile[], chain: FallbackChain): string {
  return chain.ids.map((id) => `→ ${profiles.find((p) => p.id === id)?.name ?? id}`).join(' ');
}

export function formatUsd(value: number): string {
  return `$${value.toFixed(2)}`;
}

/** Budget in plain words, for the profile list. */
export function budgetLabel(profile: AiProfile, kind: AiProviderKind): string {
  const atOnce = `${profile.budget.atOnce} at once`;
  if (kind === 'api') {
    const cap = profile.budget.costPerDay;
    return `${cap == null ? 'No daily limit' : `${formatUsd(cap)} a day`} · ${atOnce}`;
  }
  const cap = profile.budget.perHour;
  return `${cap == null ? 'No hourly limit' : `${cap} an hour`} · ${atOnce}`;
}

/** Today's use in plain words, against the budget. */
export function usageLabel(profile: AiProfile, kind: AiProviderKind): string {
  const { todayAsks, todayCost, thisHour } = profile.usage;
  const asks = `${todayAsks} ask${todayAsks === 1 ? '' : 's'}`;
  if (kind === 'api') {
    const cap = profile.budget.costPerDay;
    return `${formatUsd(todayCost)}${cap == null ? '' : ` of ${formatUsd(cap)}`} today · ${asks}`;
  }
  const cap = profile.budget.perHour;
  return `${thisHour}${cap == null ? '' : ` of ${cap}`} this hour · ${asks} today`;
}

/** Share of the budget used (0–1), or null when there is no limit. */
export function usageShare(profile: AiProfile, kind: AiProviderKind): number | null {
  if (kind === 'api') {
    const cap = profile.budget.costPerDay;
    return cap ? Math.min(1, profile.usage.todayCost / cap) : null;
  }
  const cap = profile.budget.perHour;
  return cap ? Math.min(1, profile.usage.thisHour / cap) : null;
}

/** Why temperature is off for this provider (and thinking level), or null when it is used. */
export function temperatureNote(provider: AiProviderOption | null, thinking: AiThinking | null): string | null {
  if (!provider) return 'Pick a model first.';
  if (provider.temperatureIgnored) return provider.temperatureIgnored;
  // DeepSeek (dual-mode): thinking mode ignores temperature (catalog notes).
  if (provider.id === 'deepseek' && thinking !== 'off') return 'Ignored while thinking is on.';
  return null;
}

/** Keep the thinking level when the new model takes it (null = model default stays); else its lowest. */
export function thinkingFor(model: AiModelOption | null, current: AiThinking | null): AiThinking | null {
  if (current === null) return null;
  if (!model || model.thinking.length === 0) return null;
  return model.thinking.includes(current) ? current : model.thinking[0];
}

/** What a use needs that the chosen model can't do, in plain words (null = fine). */
export function needsMismatch(
  use: AiUse,
  provider: AiProviderOption | null,
  model: AiModelOption | null
): string | null {
  if (!model || !provider) return 'Its model is no longer listed.';
  if (use.needs.pictures && !model.pictures) return `${model.name} can't see pictures.`;
  if (use.needs.sound && !model.sound) return `${model.name} can't hear sound.`;
  return null;
}


/** Fresh unique id from a name ("Camera questions" → "camera-questions-2" when taken). */
export function profileIdFor(name: string, taken: ReadonlySet<string>): string {
  const base =
    name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-|-$/g, '') || 'profile';
  let id = base;
  for (let n = 2; taken.has(id); n += 1) id = `${base}-${n}`;
  return id;
}

const THINKING_ORDER: AiThinking[] = ['off', 'minimal', 'low', 'medium', 'high'];

/**
 * Thinking levels a catalog row takes, from its `reasoning_efforts` (`none` → off; xhigh/max have no
 * profile level) plus `thinking_off_type` (the model can switch up-front thinking off). A row with no
 * efforts: off only.
 */
export function catalogThinkingLevels(row: AiCatalogModelRow): AiThinking[] {
  const out = new Set<AiThinking>();
  for (const effort of row.reasoning_efforts ?? []) {
    if (effort === 'none') out.add('off');
    else if ((THINKING_ORDER as string[]).includes(effort)) out.add(effort as AiThinking);
  }
  if (row.thinking_off_type) out.add('off');
  if (out.size === 0) out.add('off');
  return THINKING_ORDER.filter((t) => out.has(t));
}

function catalogPrice(row: AiCatalogModelRow): AiModelOption['price'] {
  const input = Number(row.pricing?.input_per_1m_tokens);
  const output = Number(row.pricing?.output_per_1m_tokens);
  return Number.isFinite(input) && Number.isFinite(output) ? { input, output } : undefined;
}

/**
 * The picker's catalog rows grouped into profile providers (kind, models, temperature rule, readiness).
 * `kindOf` / `notReadyOf` come from the controller (plan tools and local servers: their live status).
 */
export function aiProvidersFromCatalog(args: {
  models: readonly AiCatalogModelRow[];
  providers: readonly CatalogProviderRow[];
  kindOf: (providerId: string, hosting: string | null | undefined) => AiProviderKind;
  notReadyOf: (providerId: string) => string | null;
  temperatureIgnored: Record<string, string>;
}): AiProviderOption[] {
  const byId = new Map<string, AiProviderOption>();
  for (const row of args.models) {
    let provider = byId.get(row.provider_id);
    if (!provider) {
      const meta = args.providers.find((p) => p.id === row.provider_id);
      const kind = args.kindOf(row.provider_id, meta?.hosting ?? row.hosting);
      provider = {
        id: row.provider_id,
        label: meta?.display_name || row.provider_id,
        kind,
        models: [],
        temperatureIgnored:
          kind === 'plan'
            ? `${meta?.display_name || row.provider_id} sets its own.`
            : (args.temperatureIgnored[row.provider_id] ?? null),
        notReady: args.notReadyOf(row.provider_id)
      };
      byId.set(row.provider_id, provider);
    }
    const modalities = row.modalities ?? [];
    provider.models.push({
      ref: row.id,
      name: row.display_name,
      thinking: row.ai_thinking ?? catalogThinkingLevels(row),
      pictures: modalities.includes('image_in'),
      sound: modalities.includes('audio_in'),
      price: provider.kind === 'api' ? catalogPrice(row) : undefined
    });
  }
  return [...byId.values()];
}

// ── local-server / plan-tool rows of the Providers list: status word + tooltip facts ───

export function serverStatus(server: LocalServerStatus): ProviderRowStatus {
  const name = LOCAL_SERVER_KIND_LABELS[server.provider_id] ?? server.provider_id;
  if (server.state === 'up') return { tone: 'ok', word: 'up', title: `${name} is up` };
  if (server.state === 'down') {
    return { tone: 'warn', word: 'down', title: `${name} is down: ${server.error ?? "can't connect"}` };
  }
  if (server.state === 'no_address') return { tone: 'off', word: 'no address', title: `${name} has no address set` };
  return { tone: 'off', word: 'not checked', title: `${name} has not been checked yet` };
}

/** "qwen3-vl-8b (loaded by Hiro, idle 3 min)" for each loaded model, or "nothing loaded". */
export function loadedWords(server: LocalServerStatus): string {
  const loaded = server.models.filter((m) => m.loaded || m.loaded_by_core);
  if (!loaded.length) return 'nothing loaded';
  return loaded
    .map((m) => {
      const name = m.display_name || m.name;
      if (!m.loaded_by_core) return `${name} loaded`;
      const idle = m.idle_s != null ? `, idle ${Math.floor(m.idle_s / 60)} min` : '';
      return `${name} loaded by Hiro${idle}`;
    })
    .join(', ');
}

export function serverInfo(server: LocalServerStatus, usedBy: readonly string[], now: Date = new Date()): string {
  return [
    server.base_url ?? 'No address',
    server.state === 'down' ? (server.error ?? "Can't connect") : loadedWords(server),
    `unloads a model idle ${server.unload_idle_min} min`,
    server.provider_id === 'lm_studio' ? `loads with context ${server.context}, batch ${server.batch}` : null,
    `checked ${humanDateTime(server.checked_at, now)}`,
    usedBy.length ? `used by ${usedBy.join(', ')}` : 'no profile uses it'
  ]
    .filter(Boolean)
    .join(' · ');
}

export function planToolStatus(tool: PlanToolStatus): ProviderRowStatus {
  if (!tool.installed) return { tone: 'off', word: 'not installed', title: `${tool.name} is not installed` };
  if (!tool.signed_in) return { tone: 'off', word: 'signed out', title: `${tool.name} is signed out` };
  if (tool.attention) return { tone: 'warn', word: 'expires soon', title: `${tool.name}'s sign-in ends soon` };
  return { tone: 'ok', word: 'signed in', title: `${tool.name} is signed in` };
}

/** Sign-in end in plain words ("Ends Sat, Nov 28, 3:02 AM", "OK"). */
export function signInExpiryWords(tool: PlanToolStatus, now: Date = new Date()): string {
  if (!tool.installed) return 'Not installed';
  if (!tool.signed_in) return 'Not signed in';
  if (!tool.sign_in_ends_at) return 'OK';
  return `${tool.attention ? 'Ends soon: ' : 'Ends '}${humanDateTime(tool.sign_in_ends_at, now)}`;
}

/** "Max plan · you@example.com", or null when signed out. */
export function planAccountWords(tool: PlanToolStatus): string | null {
  if (!tool.signed_in) return null;
  return [tool.plan ? `${tool.plan} plan` : null, tool.account].filter(Boolean).join(' · ') || 'Signed in';
}

export function planToolInfo(
  tool: PlanToolStatus,
  updates: PlanUpdates | null,
  usedBy: readonly string[],
  now: Date = new Date()
): string {
  return [
    tool.problem,
    planAccountWords(tool) ?? 'Not signed in',
    `sign-in: ${signInExpiryWords(tool, now)}`,
    tool.version ? `version ${tool.version}` : null,
    updates?.last_run ? `updated ${humanDateTime(updates.last_run, now)}` : null,
    tool.queue_note,
    usedBy.length ? `used by ${usedBy.join(', ')}` : 'no profile uses it'
  ]
    .filter(Boolean)
    .join(' · ');
}
