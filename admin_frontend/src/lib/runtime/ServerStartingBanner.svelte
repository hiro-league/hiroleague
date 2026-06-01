<script lang="ts">
  /**
   * Notice rendered while the main HiroServer HTTP listener is still coming up.
   *
   * Surface this on any panel whose primary action goes through
   * ``post_invoke_sync`` (today: chat send). The banner subscribes to the
   * shared ``serverReadiness`` store and disappears the moment readiness
   * flips to true.
   *
   * Mounting the component is enough to keep the poll loop alive — it calls
   * ``subscribe()`` on mount.
   */
  import { onMount } from 'svelte';
  import { Loader2 } from '@lucide/svelte';
  import { serverReadiness } from '$lib/runtime/server-readiness.svelte';
  import { cn } from '$lib/utils';

  type Props = {
    /** Override the default copy. */
    message?: string;
    class?: string;
  };

  let {
    message = 'HiroServer is still starting up — message send will become available momentarily.',
    class: className
  }: Props = $props();

  onMount(() => serverReadiness.subscribe());
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
      <strong class="font-sans">Server starting…</strong>
      <span class="block">{message}</span>
    </div>
  </div>
{/if}
