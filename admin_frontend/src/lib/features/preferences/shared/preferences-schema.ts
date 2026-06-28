import type { PreferenceFieldMeta } from '$lib/api/preferences-schema';
import type { PreferencePath } from '$lib/api/generated/preferences-paths.generated';

export type { PreferencePath };
export type PreferencesSchemaMap = Record<string, PreferenceFieldMeta>;

// #6: `path` is the generated dotted-path union, so a typo or renamed field is a compile error.
// Returns null when the live schema lacks the path (still possible if the server is older).
export function preferenceFieldMeta(
  schema: PreferencesSchemaMap | null | undefined,
  path: PreferencePath
): PreferenceFieldMeta | null {
  return schema?.[path] ?? null;
}

export function preferenceNumberBounds(
  meta: PreferenceFieldMeta | null | undefined
): { min?: number; max?: number; step?: number } {
  if (!meta) return {};
  return {
    min: meta.min,
    max: meta.max,
    step: meta.step
  };
}

export function preferenceHint(meta: PreferenceFieldMeta | null | undefined): string | undefined {
  const hint = meta?.description?.trim();
  return hint || undefined;
}

/** Display-only flag: advanced fields are hidden until the "show advanced" toggle is on. */
export function preferenceIsAdvanced(meta: PreferenceFieldMeta | null | undefined): boolean {
  return meta?.advanced === true;
}
