<script lang="ts">
  import { Radio, Router, Server, Terminal } from '@lucide/svelte';
  import type { LogSourceFilter } from '$lib/api/logs';

  type Props = {
    source: LogSourceFilter;
    size?: number;
    class?: string;
  };

  let { source, size = 12, class: className = '' }: Props = $props();
</script>

{#if source === 'server'}
  <Server strokeWidth={2} {size} class={className} aria-hidden="true" />
{:else if source === 'channels'}
  <Radio strokeWidth={2} {size} class={className} aria-hidden="true" />
{:else if source === 'gateway'}
  <Router strokeWidth={2} {size} class={className} aria-hidden="true" />
{:else if source === 'cli'}
  <Terminal strokeWidth={2} {size} class={className} aria-hidden="true" />
{/if}
