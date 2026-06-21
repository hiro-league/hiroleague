import type { WorkspacePreferences } from '$lib/api/preferences';

/** Read-only / UI-only fields — never sent in the PATCH payload. */
const SKIP_PATHS = new Set([
  'version',
  'knowledge.default_embedding_model_resolved',
  'knowledge.default_embedding_model_locked',
  'knowledge.answering.model_resolved',
  'knowledge.answering.model_resolved_source',
  // Backend-computed read-only property mirrored into the graph payload — never a write path.
  'graph.embedder_model_resolved',
  'image_profiles',
  'llm.default_image_gen',
  'llm.default_image_profile'
]);

/** Subtrees the backend expects as a single path write (not per-leaf patches). */
const WHOLE_OBJECT_PATHS = new Set([
  'tuning_profiles',
  'graph.eval.answer_prompts',
  'graph.eval.retrieval_agent_prompts'
]);

/** Nullable model-id paths — empty string is coerced to null on save. */
const NULLABLE_MODEL_PATHS = new Set([
  'llm.default_chat',
  'llm.default_stt',
  'llm.default_tts',
  'knowledge.default_embedding_model',
  'knowledge.answering.model',
  'knowledge.retrieval.reranker.model_id',
  'graph.extraction_model',
  'graph.small_model',
  'graph.embedder_model',
  'graph.reranker.model_id',
  'graph.eval.answer_model',
  'graph.eval.judge_model'
]);

/** Nullable string paths — blank is coerced to null on save. */
const NULLABLE_STRING_PATHS = new Set(['graph.reranker.device']);

export function cloneWorkspacePreferences(prefs: WorkspacePreferences): WorkspacePreferences {
  return JSON.parse(JSON.stringify(prefs)) as WorkspacePreferences;
}

function valuesEqual(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function serializeLeaf(path: string, value: unknown): unknown {
  // Model ids and the reranker device coerce empty/whitespace-only strings to null on save,
  // so a cleared picker persists as null (backend fallback) rather than an empty string.
  if (NULLABLE_MODEL_PATHS.has(path) || NULLABLE_STRING_PATHS.has(path)) {
    if (value == null) return null;
    if (typeof value === 'string' && !value.trim()) return null;
  }
  return value;
}

/**
 * Walk baseline vs draft. When `edits` is omitted, returns on the first patchable diff
 * (cheap dirty probe). When `edits` is provided, collects every changed leaf path.
 */
function walkPreferenceDiff(
  before: unknown,
  after: unknown,
  path: string,
  edits?: Record<string, unknown>
): boolean {
  if (path && SKIP_PATHS.has(path)) return false;

  if (path && WHOLE_OBJECT_PATHS.has(path)) {
    const serialized = serializeLeaf(path, after);
    if (serialized === undefined) return false;
    if (!valuesEqual(before, serialized)) {
      if (edits) edits[path] = serialized;
      return true;
    }
    return false;
  }

  if (!isPlainObject(before) || !isPlainObject(after)) {
    if (!path) return false;
    const serialized = serializeLeaf(path, after);
    // Never emit `undefined` — sparse draft keys can't be PATCH-cleared this way.
    if (serialized === undefined) return false;
    if (!valuesEqual(before, serialized)) {
      if (edits) edits[path] = serialized;
      return true;
    }
    return false;
  }

  let dirty = false;
  const keys = new Set([...Object.keys(before), ...Object.keys(after)]);
  for (const key of keys) {
    const childPath = path ? `${path}.${key}` : key;
    const childDirty = walkPreferenceDiff(before[key], after[key], childPath, edits);
    if (childDirty) {
      if (!edits) return true;
      dirty = true;
    }
  }
  return dirty;
}

/** Build the patch payload sent to `patchPreferences` — only changed paths. */
export function editsForSave(
  baseline: WorkspacePreferences,
  draft: WorkspacePreferences
): Record<string, unknown> {
  const edits: Record<string, unknown> = {};
  walkPreferenceDiff(baseline, draft, '', edits);
  return edits;
}

/** True when draft differs from baseline in any patchable preference path. */
export function preferencesAreDirty(
  baseline: WorkspacePreferences,
  draft: WorkspacePreferences
): boolean {
  return walkPreferenceDiff(baseline, draft, '');
}
