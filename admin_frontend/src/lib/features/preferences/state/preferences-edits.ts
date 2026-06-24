import type { WorkspacePreferences } from '$lib/api/preferences';
import type { PreferencesSchemaMap } from '$lib/features/preferences/shared/preferences-schema';
import {
  assertKnownPreferencePath,
  coercePreferenceLeafValue,
  shouldSkipPreferencePath,
  shouldWriteWholePreferencePath,
  preferencePathMeta
} from '$lib/features/preferences/shared/preferences-edits-policy';

export function cloneWorkspacePreferences(prefs: WorkspacePreferences): WorkspacePreferences {
  return JSON.parse(JSON.stringify(prefs)) as WorkspacePreferences;
}

function valuesEqual(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function serializeLeaf(
  schema: PreferencesSchemaMap,
  path: string,
  value: unknown
): unknown {
  const meta = preferencePathMeta(schema, path);
  return coercePreferenceLeafValue(meta, value);
}

/**
 * Walk baseline vs draft. When `edits` is omitted, returns on the first patchable diff
 * (cheap dirty probe). When `edits` is provided, collects every changed leaf path.
 */
function walkPreferenceDiff(
  schema: PreferencesSchemaMap,
  before: unknown,
  after: unknown,
  path: string,
  edits?: Record<string, unknown>
): boolean {
  if (path) {
    const meta = preferencePathMeta(schema, path);
    if (shouldSkipPreferencePath(meta)) {
      return false;
    }
  }

  if (path && shouldWriteWholePreferencePath(preferencePathMeta(schema, path))) {
    assertKnownPreferencePath(schema, path);
    const serialized = serializeLeaf(schema, path, after);
    if (serialized === undefined) return false;
    if (!valuesEqual(before, serialized)) {
      if (edits) edits[path] = serialized;
      return true;
    }
    return false;
  }

  if (!isPlainObject(before) || !isPlainObject(after)) {
    if (!path) return false;
    assertKnownPreferencePath(schema, path);
    const serialized = serializeLeaf(schema, path, after);
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
    const childDirty = walkPreferenceDiff(schema, before[key], after[key], childPath, edits);
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
  draft: WorkspacePreferences,
  schema: PreferencesSchemaMap
): Record<string, unknown> {
  const edits: Record<string, unknown> = {};
  walkPreferenceDiff(schema, baseline, draft, '', edits);
  return edits;
}

/** True when draft differs from baseline in any patchable preference path. */
export function preferencesAreDirty(
  baseline: WorkspacePreferences,
  draft: WorkspacePreferences,
  schema: PreferencesSchemaMap
): boolean {
  return walkPreferenceDiff(schema, baseline, draft, '');
}
