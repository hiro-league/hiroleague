<script lang="ts">
  /**
   * App-level notice while the main HiroServer HTTP listener is unavailable.
   *
   * Mount once in AdminShell (which also calls ``serverReadiness.subscribe()``).
   * Feature panels that gate actions on ``serverReadiness.ready`` do not need their
   * own copy of this banner.
   */
  import { Loader2 } from '@lucide/svelte';
  import { serverReadiness } from '$lib/runtime/server-readiness.svelte';
  import { cn } from '$lib/utils';

  type Props = {
    /** Override the default "still starting" copy. */
    startingMessage?: string;
    /** Override the default "was up, now retrying" copy. */
    unavailableMessage?: string;
    class?: string;
  };

  let {
    startingMessage = 'HiroServer is still starting up — actions that need the main HTTP listener will become available momentarily.',
    unavailableMessage = 'HiroServer is temporarily unreachable — retrying automatically.',
    class: className
  }: Props = $props();

  const title = $derived(serverReadiness.everReady ? 'Server unavailable' : 'Server starting…');
  const message = $derived(serverReadiness.everReady ? unavailableMessage : startingMessage);
</script>

{#if !serverReadiness.ready}
  <div
    class={cn(
      'flex items-start gap-3 rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-900 dark:text-amber-200',
      className
    )}
    role="status"
    aria-live="polite"
  >
    <Loader2 class="mt-0.5 h-4 w-4 shrink-0 animate-spin" aria-hidden="true" />
    <div class="flex-1 leading-snug">
      <strong class="font-sans">{title}</strong>
      <span class="block">{message}</span>
    </div>
  </div>
{/if}
