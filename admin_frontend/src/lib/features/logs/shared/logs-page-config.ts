import { ChartColumn, List, Workflow } from '@lucide/svelte';
import type { PageTab } from '$kit/ui/page-tabs.svelte';
import type { LogsPrimaryTabPreference } from '$lib/preferences/keys';

export const LOGS_TAB_DESCRIPTORS: readonly PageTab<LogsPrimaryTabPreference>[] = [
  { id: 'logs', label: 'Logs', kind: 'pane', icon: List },
  { id: 'runs', label: 'Graph runs', kind: 'pane', icon: Workflow },
  // Phase 7b: what every paid AI call adds up to (extensions' asks + Hiro's own jobs).
  { id: 'usage', label: 'AI usage', kind: 'pane', icon: ChartColumn }
];
