<script lang="ts">
  // First tab in the retrieval trace dialog — the answer the recall drafted (a placeholder when
  // the trace was opened from a node with no answer).
  let { answer = '' }: { answer?: string } = $props();
</script>

<div class="grid gap-4 text-sm leading-6">
  <div class="flex flex-wrap items-start gap-3">
    <span class="min-w-[88px] shrink-0 pt-0.5 text-xs font-medium text-muted-foreground">Answer</span>
    {#if answer}
      <span class="min-w-0 flex-1 whitespace-pre-wrap text-foreground">{answer}</span>
    {:else}
      <span class="flex-1 italic text-muted-foreground">— (no answer)</span>
    {/if}
  </div>
</div>
