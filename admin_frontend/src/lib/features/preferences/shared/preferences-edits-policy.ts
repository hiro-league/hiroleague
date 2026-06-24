import type { PreferenceFieldMeta } from '$lib/api/preferences-schema';
import type { PreferencesSchemaMap } from './preferences-schema';

export function preferencePathMeta(
  schema: PreferencesSchemaMap,
  path: string
): PreferenceFieldMeta | undefined {
  return schema[path];
}

export function shouldSkipPreferencePath(meta: PreferenceFieldMeta | undefined): boolean {
  return Boolean(meta?.readOnly || meta?.preferencesSaveSkip);
}

export function shouldWriteWholePreferencePath(meta: PreferenceFieldMeta | undefined): boolean {
  return Boolean(meta?.writeWhole);
}

export function coercePreferenceLeafValue(
  meta: PreferenceFieldMeta | undefined,
  value: unknown
): unknown {
  if (!meta?.nullable) {
    return value;
  }
  if (meta.model_kind || meta.type === 'string') {
    if (value == null) {
      return null;
    }
    if (typeof value === 'string' && !value.trim()) {
      return null;
    }
  }
  return value;
}

// Intentional all-or-nothing: the diff walker throws on the FIRST unknown leaf, aborting the
// whole save rather than silently dropping it. An unknown path means the draft and the running
// server's schema disagree (frontend newer than server, or a renamed field) — a real bug we want
// loud. Do NOT soften this into a per-field skip; that reintroduces the silent-drift this replaced.
export function assertKnownPreferencePath(schema: PreferencesSchemaMap, path: string): void {
  if (!path) {
    return;
  }
  if (path in schema) {
    return;
  }
  throw new Error(
    `Unknown preference path "${path}" — missing from /preferences/schema field map`
  );
}
