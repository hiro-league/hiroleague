import { List, Workflow } from '@lucide/svelte';
import type { AdminTabDescriptor } from '$lib/components/page/tab-types';
import type { LogsPrimaryTabPreference } from '$lib/preferences/keys';

export const LOGS_TAB_DESCRIPTORS: readonly AdminTabDescriptor<LogsPrimaryTabPreference>[] = [
  { id: 'logs', label: 'Logs', kind: 'pane', icon: List },
  { id: 'runs', label: 'Graph runs', kind: 'pane', icon: Workflow }
];
