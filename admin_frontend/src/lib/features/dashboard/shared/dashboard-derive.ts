export type ActiveProviderRow = {
  display_name?: string | null;
  provider_id: string;
};

export function activeProviderDisplayNames(rows: ActiveProviderRow[], limit = 2): string[] {
  return rows.map((provider) => provider.display_name || provider.provider_id).slice(0, limit);
}

export function activeProviderOverflowCount(total: number, shownLimit = 2): number {
  return Math.max(total - shownLimit, 0);
}
