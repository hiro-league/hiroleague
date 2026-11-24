import { ChartColumn, List, Waypoints, Workflow } from '@lucide/svelte';
import type { PageTab } from '$kit/ui/page-tabs.svelte';
import type { LogsPrimaryTabPreference } from '$lib/preferences/keys';
import type { CoreFeature } from '$lib/shell/core-access';

export const LOGS_TAB_DESCRIPTORS: readonly PageTab<LogsPrimaryTabPreference>[] = [
  { id: 'logs', label: 'Logs', kind: 'pane', icon: List },
  // Logging and tracing plan, phase 6b: the list of stories, each drawn by its kind
  { id: 'stories', label: 'Stories', kind: 'pane', icon: Waypoints },
  { id: 'runs', label: 'Graph runs', kind: 'pane', icon: Workflow },
  // Phase 7b: what every paid AI call adds up to (extensions' asks + Hiro's own jobs).
  { id: 'usage', label: 'AI usage', kind: 'pane', icon: ChartColumn }
];

/** Permissions phase 2: the core feature that opens each tab. Graph runs show what Hiro recalled about people, and
 * AI usage each person's cost, so neither comes with the logs. */
export const LOGS_TAB_FEATURE: Record<LogsPrimaryTabPreference, CoreFeature> = {
  logs: 'logs',
  stories: 'logs',
  runs: 'logs.runs',
  usage: 'logs.usage'
};
