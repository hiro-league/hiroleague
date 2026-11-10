/**
 * Mapping between the AI API shapes (`$lib/api/ai`, preferences `ai.profiles`) and what the AI pages
 * edit (`ai-types.ts`). Pure: no Svelte, no I/O.
 */
import type { AiJobRow, AiLocalModel, AiProfileRow, AiTryPayload, AiUsesExtension, PlanToolStatus } from '$lib/api/ai';
import type { AiProfile as AiProfilePrefs } from '$lib/api/generated/preferences.generated';
import type { AiCatalogModelRow, AiJob, AiProfile, AiThinking, AiTryResult, AiUse, AiUsesGroup } from './ai-types';

/** A row of `GET /ai/profiles` → the profile the list and editor work with. */
export function profileFromRow(row: AiProfileRow): AiProfile {
  return {
    id: row.id,
    name: row.label,
    model: row.model,
    thinking: row.thinking ?? null,
    temperature: row.temperature,
    maxTokens: row.max_tokens,
    context: row.num_ctx,
    instructions: row.instructions ?? '',
    budget: {
      costPerDay: row.budget.max_cost_day,
      perHour: row.budget.max_per_hour,
      atOnce: row.budget.at_once
    },
    fallbackId: row.fallback,
    usage: { todayAsks: row.today.asks, todayCost: row.today.cost, thisHour: row.today.this_hour },
    server: { kind: row.kind, providerLabel: row.provider_label, notReady: row.not_ready },
    preset: row.preset ?? null,
    jobs: row.jobs ?? []
  };
}

/** A job of `GET /ai/profiles` (Phase 7b step 5) → the Uses tab's Hiro row. */
export function jobFromRow(row: AiJobRow): AiJob {
  return {
    id: row.id,
    label: row.label,
    path: row.path,
    profileId: row.profile_id,
    defaultProfileId: row.default_profile_id,
    fallsBackTo: row.falls_back_to,
    model: row.model
  };
}

/** Empty / non-positive limits mean "no limit" (the backend wants > 0 or null). */
function positiveOrNull(value: number | null | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : null;
}

/** The profile as `ai.profiles.<id>` stores it (preferences PATCH body, Try it draft). */
export function profileToPrefs(profile: AiProfile): AiProfilePrefs {
  return {
    label: profile.name.trim(),
    model: profile.model,
    thinking: profile.thinking,
    temperature: profile.temperature,
    max_tokens: positiveOrNull(profile.maxTokens),
    // The editor clears context for non-local models.
    num_ctx: positiveOrNull(profile.context),
    // Extra instructions are optional: empty means none.
    instructions: profile.instructions.trim(),
    max_cost_day: positiveOrNull(profile.budget.costPerDay),
    max_per_hour: positiveOrNull(profile.budget.perHour) === null ? null : Math.round(profile.budget.perHour ?? 0),
    at_once: Math.min(4, Math.max(1, Math.round(profile.budget.atOnce || 1))),
    fallback: profile.fallbackId || null,
    // Phase 7b step 5: a job's default profile stays one when edited (its Restore default needs it).
    preset: profile.preset ?? null
  };
}

/** `GET /ai/uses` → the groups (one per extension) and a flat list of uses. */
export function usesFromPayload(extensions: readonly AiUsesExtension[]): { groups: AiUsesGroup[]; uses: AiUse[] } {
  const groups: AiUsesGroup[] = [];
  const uses: AiUse[] = [];
  for (const ext of extensions) {
    groups.push({ extension: ext.extension, extensionId: ext.extension_id, connected: ext.connected, asOf: ext.as_of });
    for (const row of ext.uses) {
      uses.push({
        id: row.key,
        extension: ext.extension,
        label: row.name,
        needs: {
          pictures: row.pictures > 0 ? row.pictures : undefined,
          sound: row.sound || undefined,
          json: row.json
        },
        profileId: row.profile_id,
        status: row.status === 'ok' ? undefined : row.status
      });
    }
  }
  return { groups, uses };
}

/** Models a local server reported → catalog-shaped chat rows for the shared model picker. */
export function localModelCatalogRows(models: readonly AiLocalModel[]): AiCatalogModelRow[] {
  return models.map((m) => ({
    id: m.id,
    provider_id: m.provider_id,
    display_name: m.loaded ? `${m.display_name || m.name} (loaded)` : m.display_name || m.name,
    model_kind: 'chat',
    hosting: 'local',
    modalities: m.vision ? ['text', 'image_in'] : ['text'],
    features: m.reasoning ? ['reasoning'] : [],
    // A local model that reasons can usually switch it off; levels beyond on/off aren't reported.
    reasoning_efforts: m.reasoning ? ['none', 'medium'] : [],
    free: true
  }));
}

const THINKING_VALUES: readonly string[] = ['off', 'minimal', 'low', 'medium', 'high'];

/**
 * A plan tool's models (as the tool lists them) → catalog-shaped chat rows for the shared model
 * picker (the catalog has the plan providers but no model rows for them). `thinking: []` = the
 * tool's own default only, so the editor offers just "Model default".
 */
export function planModelCatalogRows(tool: PlanToolStatus): AiCatalogModelRow[] {
  return tool.models.map((m) => {
    const levels = m.thinking.filter((t): t is AiThinking => THINKING_VALUES.includes(t));
    return {
      id: `${tool.id}:${m.id}`,
      provider_id: tool.id,
      display_name: m.name,
      model_kind: 'chat',
      hosting: 'plan',
      modalities: ['text', 'image_in'],
      features: levels.some((t) => t !== 'off') ? ['reasoning'] : [],
      notes: m.about || null,
      ai_thinking: levels
    };
  });
}

function costWords(answer: NonNullable<AiTryPayload['answer']>, kind: string | undefined): string {
  if (answer.plan) return answer.estimate != null ? `on your plan (about $${answer.estimate.toFixed(4)})` : 'on your plan';
  if (kind === 'local') return 'free, in the home';
  return answer.cost != null ? `about $${answer.cost.toFixed(4)}` : 'price unknown';
}

/** Try it's answer → what the editor shows; an error comes back as `{ error }`. */
export function tryResultFrom(
  payload: AiTryPayload,
  kind: string | undefined
): { result: AiTryResult | null; error: string | null } {
  if (!payload.ok || !payload.answer) {
    const err = payload.error;
    const notes = err?.notes?.length ? ` (${err.notes.join('; ')})` : '';
    return { result: null, error: `${err?.message ?? 'The ask failed.'}${notes}` };
  }
  const a = payload.answer;
  return {
    result: {
      answer: a.text,
      model: a.model,
      seconds: a.ms / 1000,
      tokensIn: a.tokens_in,
      tokensOut: a.tokens_out,
      cost: costWords(a, kind),
      notes: a.notes
    },
    error: null
  };
}
