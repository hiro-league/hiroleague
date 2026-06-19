export type GraphFilterOption = { value: string; label: string; weight: number };

export function sortFilterOptions(
  options: GraphFilterOption[],
  sortMode: 'weight' | 'alpha'
): GraphFilterOption[] {
  return [...options].sort((a, b) =>
    sortMode === 'alpha'
      ? a.label.localeCompare(b.label)
      : b.weight - a.weight || a.label.localeCompare(b.label)
  );
}

export function filterOptionsBySearch(
  options: GraphFilterOption[],
  search: string
): GraphFilterOption[] {
  const q = search.trim().toLowerCase();
  if (!q) return options;
  return options.filter((o) => o.label.toLowerCase().includes(q));
}

/** "all N" when fully selected, "0/N" when empty, "k/N" partial. */
export function filterSelectionSummary(total: number, selectedCount: number): string {
  if (total > 0 && selectedCount === total) return `all ${total}`;
  if (selectedCount === 0) return `0/${total}`;
  return `${selectedCount}/${total}`;
}

export function filterDropdownPlaceholder(label: string, searchPlaceholder?: string): string {
  return searchPlaceholder ?? `Search ${label}…`;
}
