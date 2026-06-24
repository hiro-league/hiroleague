import type { PreferenceFieldMeta } from '$lib/api/preferences-schema';

export type PrefSelectOption = {
  value: string;
  label: string;
  disabled?: boolean;
  title?: string;
};

export function normalizePrefSelectOptions(
  options: PrefSelectOption[] | Record<string, string>
): PrefSelectOption[] {
  if (Array.isArray(options)) return options;
  return Object.entries(options).map(([value, label]) => ({ value, label }));
}

/** Surfaces backend enum drift when labels are wired on the card. */
export function assertPrefSelectOptionsMatchEnum(
  meta: PreferenceFieldMeta | null | undefined,
  options: PrefSelectOption[]
): void {
  if (!meta?.enum?.length) return;
  const domain = new Set(meta.enum);
  for (const option of options) {
    if (!domain.has(option.value)) {
      throw new Error(
        `Select option "${option.value}" is not in schema enum for ${meta.path}: [${meta.enum.join(', ')}]`
      );
    }
  }
  for (const value of meta.enum) {
    if (!options.some((option) => option.value === value)) {
      throw new Error(`Missing select label for schema enum value "${value}" on ${meta.path}`);
    }
  }
}
