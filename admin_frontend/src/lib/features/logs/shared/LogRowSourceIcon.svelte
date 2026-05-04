<script lang="ts">
  import { CircleHelp } from '@lucide/svelte';
  import LogSourceIcon from './LogSourceIcon.svelte';
  import { logRowSourceFilter } from './logs-ui';

  type Props = {
    rowSource: string;
    size?: number;
    class?: string;
  };

  let { rowSource, size = 12, class: className = '' }: Props = $props();

  const filter = $derived(logRowSourceFilter(rowSource));
</script>

{#if filter}
  <LogSourceIcon source={filter} {size} class={className} />
{:else}
  <CircleHelp strokeWidth={2} {size} class={className} aria-hidden="true" />
{/if}
