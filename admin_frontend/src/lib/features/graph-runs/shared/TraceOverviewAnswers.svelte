<script lang="ts">
  // First tab in the retrieval trace dialog — gold reference vs model answer (always shown;
  // empty placeholders when opened outside eval context).
  let {
    idealAnswer = '',
    llmAnswer = ''
  }: { idealAnswer?: string; llmAnswer?: string } = $props();
</script>

<div class="grid gap-4 text-sm leading-6">
  <div class="flex flex-wrap items-start gap-3">
    <span class="min-w-[88px] shrink-0 pt-0.5 text-xs font-medium text-muted-foreground">Gold Answer</span>
    {#if idealAnswer}
      <span class="min-w-0 flex-1 whitespace-pre-wrap text-foreground">{idealAnswer}</span>
    {:else}
      <span class="flex-1 italic text-muted-foreground">— (no gold answer)</span>
    {/if}
  </div>
  <div class="flex flex-wrap items-start gap-3">
    <span class="min-w-[88px] shrink-0 pt-0.5 text-xs font-medium text-muted-foreground">Our Answer</span>
    {#if llmAnswer}
      <span class="min-w-0 flex-1 whitespace-pre-wrap text-foreground">{llmAnswer}</span>
    {:else}
      <span class="flex-1 italic text-muted-foreground">— (no answer)</span>
    {/if}
  </div>
</div>
