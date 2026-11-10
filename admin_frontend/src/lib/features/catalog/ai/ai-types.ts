/**
 * Shapes the Phase 7a AI pages work with (AI profiles, Uses, and the Providers tab's local-server /
 * plan-tool rows). Mapped from the API (`$lib/api/ai`) in `ai-api-mapping.ts`; local servers and plan
 * tools use the API types directly.
 */

/** Where a model runs: a paid API, a local server in the home, or a plan tool (Claude Code, Codex). */
export type AiProviderKind = 'api' | 'local' | 'plan';

export type AiThinking = 'off' | 'minimal' | 'low' | 'medium' | 'high';

export type AiModelOption = {
  /** `provider:model` — what a profile stores. */
  ref: string;
  name: string;
  /** Thinking levels this model takes (first = lowest). */
  thinking: AiThinking[];
  pictures: boolean;
  sound: boolean;
  /** API models only: USD per 1M tokens. */
  price?: { input: number; output: number };
  /** Local models only: loaded on the server right now. */
  loaded?: boolean;
};

export type AiProviderOption = {
  id: string;
  label: string;
  kind: AiProviderKind;
  models: AiModelOption[];
  /** Why temperature does nothing here (null = it is used). */
  temperatureIgnored: string | null;
  /** Why it can't answer now (server down, signed out); null = ready. */
  notReady: string | null;
};

export type AiProfileBudget = {
  /** API: USD a day (null = no limit). */
  costPerDay: number | null;
  /** Plan tools and local: questions an hour (null = no limit). */
  perHour: number | null;
  /** Questions worked on together, 1–4. */
  atOnce: number;
};

export type AiProfileUsage = {
  todayAsks: number;
  todayCost: number;
  thisHour: number;
};

export type AiProfile = {
  id: string;
  name: string;
  /** `provider:model`. */
  model: string;
  /** null = the model's default. */
  thinking: AiThinking | null;
  /** 0–2; null = the provider's default. */
  temperature: number | null;
  maxTokens: number | null;
  /** Local models only (num_ctx). */
  context: number | null;
  instructions: string;
  budget: AiProfileBudget;
  fallbackId: string | null;
  usage: AiProfileUsage;
  /** From the server's profile list: where it runs and whether it can answer now (absent on a new draft). */
  server?: { kind: AiProviderKind; providerLabel: string; notReady: string | null };
  /** Phase 7b step 5: the job this profile is the default of ("chat", …); null = the owner's own.
   *  A default profile shows "Default", can't be deleted and has Restore default. Kept on save. */
  preset: string | null;
  /** Phase 7b step 5: ids of Hiro's jobs whose own field points at it (from the server's list). */
  jobs: string[];
};

/** One of Hiro's own jobs on the Uses tab (Phase 7b step 5): its field points at one AI profile. */
export type AiJob = {
  id: string;
  label: string;
  /** The preference field to PATCH with the picked profile id (null = not set). */
  path: string;
  profileId: string | null;
  defaultProfileId: string;
  fallsBackTo: string | null;
  /** The model the job runs with now (saved); null = nothing can run it. */
  model: string | null;
};

export type AiUseNeeds = {
  /** The most pictures it sends (absent = none). */
  pictures?: number;
  /** A sound clip. */
  sound?: boolean;
  json?: boolean;
};

/** One thing an extension asks an AI for, pointed at a profile in the core's admin. */
export type AiUse = {
  /** The `ai.uses` key: `"<extension name>:<use id>"`. */
  id: string;
  extension: string;
  label: string;
  needs: AiUseNeeds;
  profileId: string | null;
  /** After a refresh: `new` = just offered by the extension; `removed` = no longer offered. */
  status?: 'new' | 'removed';
};

export type AiTryResult = {
  answer: string;
  model: string;
  seconds: number;
  tokensIn: number;
  tokensOut: number;
  /** "about $0.0012", "on your plan", "free, in the home". */
  cost: string;
  /** Profiles passed over on the way (fallbacks), in plain words. */
  notes: string[];
};

/** One extension's group on the Uses tab. */
export type AiUsesGroup = {
  extension: string;
  /** null = no longer paired (its uses can only be forgotten). */
  extensionId: string | null;
  connected: boolean | null;
  asOf: string | null;
};

/**
 * A catalog chat row as `/catalog/models` returns it, plus the thinking fields the server's model
 * spec also carries (`reasoning_efforts`, `thinking_off_type`) that `CatalogModelRow` doesn't type.
 */
export type AiCatalogModelRow = import('$lib/api/catalog').CatalogModelRow & {
  reasoning_efforts?: string[];
  thinking_off_type?: string | null;
  /** Thinking levels stated outright (plan tools' models); wins over the catalog fields. */
  ai_thinking?: AiThinking[];
};

/** A local-server / plan-tool provider row's status: dot tone + the short word under it (+ hover title). */
export type ProviderRowStatus = { tone: 'ok' | 'warn' | 'off'; word: string; title: string };
