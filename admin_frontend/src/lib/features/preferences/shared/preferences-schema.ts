import type { PreferenceFieldMeta } from '$lib/api/preferences-schema';

export type PreferencesSchemaMap = Record<string, PreferenceFieldMeta>;

export function preferenceFieldMeta(
  schema: PreferencesSchemaMap | null | undefined,
  path: string
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
