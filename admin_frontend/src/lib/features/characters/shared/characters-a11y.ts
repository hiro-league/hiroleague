/**
 * Stable DOM ids for the Characters disclosure regions. Centralized so the collapse
 * button (`aria-controls`) and the controlled region (`id`) can't drift.
 */
export function resolvedDetailsId(segment: 'full' | 'llm' | 'voice'): string {
  return `character-resolved-${segment}-details`;
}
