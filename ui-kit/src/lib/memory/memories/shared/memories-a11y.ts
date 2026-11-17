// Stable DOM ids for the memories table's tab and panel. In one place so the host page's tab button
// (`aria-controls`, `htmlId`) and the panel (`id`, `aria-labelledby`) can't drift.
// UI kit: from the HiroLeague admin's Memories page.
export const MEMORIES_A11Y = {
	memoriesTab: 'memories-tab-memories',
	memoriesPanel: 'memories-panel-memories'
} as const;
