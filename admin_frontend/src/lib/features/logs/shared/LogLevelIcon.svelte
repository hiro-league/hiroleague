<script lang="ts">
  import {
    Bug,
    CircleHelp,
    CircleX,
    Info,
    OctagonAlert,
    Sparkles,
    TriangleAlert
  } from '@lucide/svelte';
  import { isLogLevel } from './logs-ui';

  type Props = {
    level: string;
    size?: number;
    class?: string;
  };

  let { level, size = 12, class: className = '' }: Props = $props();
</script>

{#if isLogLevel(level)}
  {#if level === 'DEBUG'}
    <Bug strokeWidth={2} {size} class={className} aria-hidden="true" />
  {:else if level === 'FINEINFO'}
    <Sparkles strokeWidth={2} {size} class={className} aria-hidden="true" />
  {:else if level === 'INFO'}
    <Info strokeWidth={2} {size} class={className} aria-hidden="true" />
  {:else if level === 'WARNING'}
    <TriangleAlert strokeWidth={2} {size} class={className} aria-hidden="true" />
  {:else if level === 'ERROR'}
    <CircleX strokeWidth={2} {size} class={className} aria-hidden="true" />
  {:else if level === 'CRITICAL'}
    <OctagonAlert strokeWidth={2} {size} class={className} aria-hidden="true" />
  {/if}
{:else}
  <CircleHelp strokeWidth={2} {size} class={className} aria-hidden="true" />
{/if}
