/**
 * Stable DOM ids for the Memories page tab/panel relationship. Centralized so the
 * tab button (`aria-controls`) and the panel (`id` + `aria-labelledby`) can't drift.
 */
export const MEMORIES_A11Y = {
  memoriesTab: 'memories-tab-memories',
  memoriesPanel: 'memories-panel-memories'
} as const;
