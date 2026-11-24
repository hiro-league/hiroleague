<script lang="ts">
  // Roles and Compare: which app's features are shown, all of them or one. Each count is how many features it
  // declares, the same on both tabs. The kit's Segmented (shadcn-svelte's Toggle Group, single).
  import Segmented from '$kit/ui/segmented.svelte';
  import type { AccessSource } from '$lib/api/people';
  import { ALL_APPS } from '../state/roles-controller.svelte';

  interface Props {
    sources: AccessSource[];
    value: string;
    onchange: (next: string) => void;
  }
  let { sources, value, onchange }: Props = $props();

  const options = $derived([
    { value: ALL_APPS, label: 'All', count: sources.reduce((n, s) => n + s.features.length, 0) },
    ...sources.map((s) => ({ value: s.id, label: s.name, count: s.features.length }))
  ]);
</script>

<Segmented class="flex-wrap" label="Apps shown" {options} {value} {onchange} />
