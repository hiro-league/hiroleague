/**
 * AI profiles and uses (Phase 7a) — `/api/ai/...` (hirocli `admin_svelte/routes/ai.py` over
 * `tools/ai.py`). Profiles are created, changed and deleted through the preferences API
 * (`ai.profiles.<id>`, like `image_profiles`); these routes read them with today's use and
 * readiness, Try one, and manage `ai.uses`. Contract: `docs/phase7a-ai-asks-design.md`.
 */
import type { UsageRow } from '$lib/features/ai-usage/ai-usage';
import { apiRequest } from './client';
import type { AiProfile as AiProfilePrefs } from './generated/preferences.generated';

export type AiProfileKind = 'api' | 'local' | 'plan';

/** One row of `GET /ai/profiles` (`services/ai_ask/catalog_view.profile_rows`). */
export type AiProfileRow = {
  id: string;
  label: string;
  model: string;
  provider: string;
  provider_label: string;
  kind: AiProfileKind;
  thinking: AiProfilePrefs['thinking'];
  temperature: number | null;
  max_tokens: number | null;
  num_ctx: number | null;
  instructions: string;
  budget: { max_cost_day: number | null; max_per_hour: number | null; at_once: number };
  budget_hint: string;
  today: { asks: number; cost: number; this_hour: number };
  fallback: string | null;
  fallback_chain: string[];
  ready: boolean;
  not_ready: string | null;
  /** Phase 7b step 5: the job this profile is the default of ("chat", "memory", …; null = the owner's
   *  own profile) — the admin shows "Default", hides Delete and offers Restore default. */
  preset: string | null;
  /** Phase 7b step 5: ids of Hiro's jobs whose own field points at this profile. */
  jobs: string[];
};

/** One of Hiro's own jobs (`services/ai_ask/catalog_view.job_rows`, Phase 7b step 5). */
export type AiJobRow = {
  id: string;
  label: string;
  /** The preference field holding the job's AI profile id (PATCH it to change the job's profile). */
  path: string;
  /** The profile the job's own field holds (null = not set: it borrows `falls_back_to`'s). */
  profile_id: string | null;
  /** The id of the profile made for the job by default. */
  default_profile_id: string;
  /** The job whose profile an unset field borrows; null = nothing (the job is off). */
  falls_back_to: string | null;
  /** The preference path whose profile supplies the model now; null when nothing is set. */
  source: string | null;
  /** The model the job runs with now (saved), and the profile it came from; null = none can run. */
  model: string | null;
  model_profile_id: string | null;
  /** The job's preset tuning (what Restore default puts back). */
  preset: { temperature: number; max_tokens: number; thinking: AiProfilePrefs['thinking'] };
};

export type AiProfilesPayload = {
  profiles: AiProfileRow[];
  uses: Record<string, string | null>;
  jobs: AiJobRow[];
};

/** A model a local server last reported (`domain/discovered_models.DiscoveredModel`). */
export type AiLocalModel = {
  id: string;
  provider_id: string;
  name: string;
  display_name: string;
  vision: boolean;
  reasoning: boolean;
  loaded: boolean;
  seen_at: string;
};

/** The `ai.ask` answer (`services/ai_ask/runner.AskAnswer`). */
export type AiAskAnswer = {
  text: string;
  profile_id: string;
  profile_name: string;
  provider: string;
  model: string;
  plan: boolean;
  ms: number;
  tokens: number;
  tokens_in: number;
  tokens_out: number;
  cost: number | null;
  estimate: number | null;
  notes: string[];
  tries: { profile_id: string; provider: string; model: string; status: string; error?: string | null; ms: number }[];
};

export type AiTryPayload = {
  ok: boolean;
  answer: AiAskAnswer | null;
  error: { code: string; message: string; notes: string[]; tries: AiAskAnswer['tries'] } | null;
};

export type AiUseRow = {
  /** `"<extension name>:<use id>"` — the `ai.uses` key. */
  key: string;
  id: string;
  name: string;
  /** 0 = none, else the most it sends. */
  pictures: number;
  sound: boolean;
  json: boolean;
  profile_id: string | null;
  status: 'ok' | 'new' | 'removed';
};

export type AiUsesExtension = {
  extension: string;
  extension_id: string | null;
  connected: boolean | null;
  /** When the extension last told the core its uses (ISO). */
  as_of: string | null;
  version: string;
  uses: AiUseRow[];
};

export type AiUsesPayload = { extensions: AiUsesExtension[]; live: boolean };

export type AiUsesRefreshPayload = {
  refreshed: { extension_id: string; extension: string; uses: number }[];
  failed: { extension_id: string; extension: string; error: string }[];
  note: string;
};

export async function listAiProfiles(): Promise<AiProfilesPayload> {
  return apiRequest<AiProfilesPayload>('/ai/profiles');
}

/** Phase 7b step 5: a job's default profile back to its preset tuning (thinking, temperature, max
 *  tokens; no context window, no instructions). Its model, name, limits and fallback stay. */
export async function restoreAiProfileDefault(
  profileId: string
): Promise<{ profile_id: string; preset: string; profile: AiProfilePrefs }> {
  return apiRequest(`/ai/profiles/${encodeURIComponent(profileId)}/restore-default`, { method: 'POST' });
}

export async function listAiLocalModels(): Promise<{ models: AiLocalModel[] }> {
  return apiRequest<{ models: AiLocalModel[] }>('/ai/local-models');
}

/** Try it: a saved profile (`profile_id`) or the editor's draft (AI profile fields). */
export async function tryAiProfile(body: {
  prompt: string;
  profile_id?: string | null;
  draft?: AiProfilePrefs | null;
  picture?: string | null;
}): Promise<AiTryPayload> {
  // A real ask (plan tools and local models can take minutes): well past the default 20 s.
  return apiRequest<AiTryPayload>('/ai/try', { method: 'POST', body, timeoutMs: 300_000 });
}

/** Phase 7b: Logs → AI usage — every paid AI call per hour in [start, end) (`UsageRow`s, named). */
export async function fetchAiUsage(start: number, end: number): Promise<{ rows: UsageRow[] }> {
  const q = new URLSearchParams({ start: new Date(start).toISOString(), end: new Date(end).toISOString() });
  return apiRequest<{ rows: UsageRow[] }>(`/ai/usage?${q}`, { timeoutMs: 60_000 });
}

export async function listAiUses(): Promise<AiUsesPayload> {
  return apiRequest<AiUsesPayload>('/ai/uses');
}

export async function setAiUse(key: string, profileId: string | null): Promise<unknown> {
  return apiRequest(`/ai/uses/${encodeURIComponent(key)}`, { method: 'PUT', body: { profile_id: profileId } });
}

export async function forgetAiUse(key: string): Promise<unknown> {
  return apiRequest(`/ai/uses/${encodeURIComponent(key)}`, { method: 'DELETE' });
}

export async function refreshAiUses(extensionId: string | null): Promise<AiUsesRefreshPayload> {
  return apiRequest<AiUsesRefreshPayload>('/ai/uses/refresh', {
    method: 'POST',
    body: { extension_id: extensionId },
    timeoutMs: 60_000
  });
}

// ── Part B: plan tools (Claude Code / Codex) and local servers ─────────────

export type PlanSignInState = 'none' | 'waiting' | 'blocked' | 'done' | 'failed' | 'expired';

/** A sign-in in progress (`services/plans/signin.SignInOut`). */
export type PlanSignIn = {
  state: PlanSignInState;
  /** The page to open. */
  link: string | null;
  /** The code to type on that page (Codex). */
  code: string | null;
  /** Waiting for the code the tool's page shows, pasted back (Claude Code). */
  takes_code: boolean;
  code_sent: boolean;
  message: string | null;
};

/** A model a plan tool offers (`services/plans/models.PlanModel`). */
export type PlanToolModel = {
  id: string;
  name: string;
  about: string;
  /** Thinking levels it takes ([] = the tool's own default only). */
  thinking: string[];
};

/** One plan tool's status (`services/plans/ops.tool_status`). */
export type PlanToolStatus = {
  id: string;
  name: string;
  installed: boolean;
  version: string | null;
  signed_in: boolean;
  account: string | null;
  plan: string | null;
  method: string | null;
  problem: string | null;
  signed_in_at: string | null;
  sign_in_ends_at: string | null;
  /** Signed out, or the sign-in ends soon. */
  attention: boolean;
  takes_code: boolean;
  models: PlanToolModel[];
  models_problem: string | null;
  sign_in: PlanSignIn;
  queue_note: string;
};

/** The nightly / on-demand npm update (`services/plans/updates.UpdateState`). */
export type PlanUpdates = {
  folder: string;
  running: boolean;
  last_run: string | null;
  ok: boolean | null;
  message: string | null;
  versions: Record<string, string>;
  next_run: string | null;
};

export type PlansPayload = { tools: PlanToolStatus[]; updates: PlanUpdates };

export type PlanTestPayload = {
  tool: string;
  ok: boolean;
  ms: number;
  answer: string | null;
  model: string | null;
  error: string | null;
};

/** A model on a local server, with whether the core loaded it (`tools/ai.LocalServerCheckTool`). */
export type LocalServerModelRow = AiLocalModel & { loaded_by_core: boolean; idle_s: number | null };

/** A local server checked now (`tools/ai.LocalServerCheckResult`). */
export type LocalServerStatus = {
  provider_id: string;
  base_url: string | null;
  online: boolean;
  error: string | null;
  models: LocalServerModelRow[];
  state: 'up' | 'down' | 'no_address' | 'unknown';
  configured: boolean;
  checked_at: string | null;
  unload_idle_min: number;
  context: number;
  batch: number;
};

export type LocalServerSettingsBody = {
  base_url?: string | null;
  unload_idle_min?: number | null;
  context?: number | null;
  batch?: number | null;
};

export async function getPlans(fresh = false): Promise<PlansPayload> {
  return apiRequest<PlansPayload>(`/ai/plans${fresh ? '?fresh=true' : ''}`, { timeoutMs: 60_000 });
}

export async function planSignIn(
  tool: string,
  action: 'start' | 'state' | 'code' | 'cancel',
  code?: string
): Promise<PlanSignIn & { tool: string }> {
  return apiRequest<PlanSignIn & { tool: string }>(`/ai/plans/${encodeURIComponent(tool)}/sign-in`, {
    method: 'POST',
    body: { action, code: code ?? null },
    timeoutMs: 60_000
  });
}

export async function planSignOut(
  tool: string
): Promise<{ tool: string; signed_out: boolean; message: string | null }> {
  return apiRequest(`/ai/plans/${encodeURIComponent(tool)}/sign-out`, { method: 'POST', timeoutMs: 60_000 });
}

export async function planTest(tool: string): Promise<PlanTestPayload> {
  // A real question through the tool: can take a couple of minutes.
  return apiRequest<PlanTestPayload>(`/ai/plans/${encodeURIComponent(tool)}/test`, {
    method: 'POST',
    timeoutMs: 300_000
  });
}

/** Starts npm in the background (it can take minutes); poll `getPlans` while `updates.running`. */
export async function updatePlans(): Promise<{ updates: PlanUpdates }> {
  return apiRequest<{ updates: PlanUpdates }>('/ai/plans/update', { method: 'POST', body: { wait: false } });
}

/** Both local server kinds, checked now. */
export async function listLocalServers(): Promise<{ servers: LocalServerStatus[] }> {
  return apiRequest<{ servers: LocalServerStatus[] }>('/ai/local-servers', { timeoutMs: 60_000 });
}

export async function checkLocalServer(
  providerId: string,
  baseUrl?: string | null
): Promise<LocalServerStatus> {
  return apiRequest<LocalServerStatus>(`/ai/local-servers/${encodeURIComponent(providerId)}/check`, {
    method: 'POST',
    body: { base_url: baseUrl ?? null },
    timeoutMs: 60_000
  });
}

export async function setLocalServer(
  providerId: string,
  body: LocalServerSettingsBody
): Promise<{ provider_id: string; base_url: string | null; unload_idle_min: number; context: number; batch: number }> {
  return apiRequest(`/ai/local-servers/${encodeURIComponent(providerId)}`, { method: 'PUT', body });
}
