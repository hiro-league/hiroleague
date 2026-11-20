<script lang="ts">
  // A story kind's icon. `unknown`: a line's story whose kind isn't written yet (before phase 6a).
  import { Layers, MessagesSquare, MousePointerClick, RefreshCw, Waypoints, Zap } from '@lucide/svelte';
  import type { StoryKind } from '$lib/api/logs';

  let { kind, size = 13, class: className = '' }: { kind: StoryKind | 'unknown'; size?: number; class?: string } = $props();
</script>

{#if kind === 'conversation'}
  <MessagesSquare strokeWidth={2} {size} class={className} aria-hidden="true" />
{:else if kind === 'event'}
  <Zap strokeWidth={2} {size} class={className} aria-hidden="true" />
{:else if kind === 'round'}
  <RefreshCw strokeWidth={2} {size} class={className} aria-hidden="true" />
{:else if kind === 'action'}
  <MousePointerClick strokeWidth={2} {size} class={className} aria-hidden="true" />
{:else if kind === 'job'}
  <Layers strokeWidth={2} {size} class={className} aria-hidden="true" />
{:else}
  <Waypoints strokeWidth={2} {size} class={className} aria-hidden="true" />
{/if}
