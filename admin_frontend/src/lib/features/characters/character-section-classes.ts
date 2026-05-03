/**
 * Shared Tailwind class strings for Characters section cards.
 *
 * Used by `CharacterSectionCard` and any sibling section that builds its own snippet `header`
 * (e.g. `CharacterPreferredModelsSection`). Keeping the strings here means we don't bring back
 * the old `.character-section-*` global utilities while still avoiding copy-paste drift.
 */
export const characterSectionTitleClass =
  'mb-1.5 mt-0 font-sans text-lg font-bold tracking-[-0.02em] text-[color-mix(in_oklab,var(--primary)_88%,var(--foreground))]';

export const characterSectionHintClass =
  'mb-4 mt-0 max-w-3xl text-sm leading-snug text-muted-foreground';
