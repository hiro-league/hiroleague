<script lang="ts">
  import { RotateCcw } from '@lucide/svelte';

  let { dirty, onReset }: { dirty: boolean; onReset: () => void } = $props();
</script>

{#if dirty}
  <button
    type="button"
    onclick={onReset}
    title="Reset to default"
    aria-label="Reset to default"
    class="ml-1 inline-flex size-3.5 shrink-0 items-center justify-center rounded text-muted-foreground/60 hover:bg-muted hover:text-foreground"
  >
    <RotateCcw size={10} aria-hidden="true" />
  </button>
{/if}
