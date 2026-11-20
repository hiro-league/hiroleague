<script lang="ts">
  // A part's icon: the core's own streams keep the Logs tab's icons; an app is a box, the phone a phone.
  import { Box, Radio, Router, Server, Smartphone, Terminal } from '@lucide/svelte';
  import { partKind } from './parts';

  let { source, size = 13, class: className = '' }: { source: string; size?: number; class?: string } = $props();
  const kind = $derived(partKind(source));
</script>

{#if kind === 'server'}
  <Server strokeWidth={2} {size} class={className} aria-hidden="true" />
{:else if kind === 'gateway'}
  <Router strokeWidth={2} {size} class={className} aria-hidden="true" />
{:else if kind === 'cli'}
  <Terminal strokeWidth={2} {size} class={className} aria-hidden="true" />
{:else if kind === 'channel'}
  <Radio strokeWidth={2} {size} class={className} aria-hidden="true" />
{:else if kind === 'device'}
  <Smartphone strokeWidth={2} {size} class={className} aria-hidden="true" />
{:else}
  <Box strokeWidth={2} {size} class={className} aria-hidden="true" />
{/if}
