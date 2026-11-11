<script lang="ts">
  /**
   * Shared warning when the knowledge SSE multiplexer stays disconnected past its
   * grace window (usually the browser connection budget is exhausted).
   */
  import { knowledgeEventStream } from '$lib/features/knowledge/shared/knowledge-event-stream.svelte';
  import Notice from '$kit/ui/notice.svelte';

  type Props = {
    class?: string;
  };

  let { class: className = 'mb-3' }: Props = $props();

  const message =
    'Live updates are disconnected — the browser may be out of connections. Close some other Hiro Admin browser tabs and they\'ll resume automatically.';
</script>

{#if knowledgeEventStream.degraded}
  <Notice tone="warning" {message} class={className} />
{/if}
