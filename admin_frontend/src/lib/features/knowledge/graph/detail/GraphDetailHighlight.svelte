<script lang="ts">
  import { highlightParts } from '../graph-detail-helpers';

  let { text, search }: { text: string; search: string } = $props();
</script>

{#each highlightParts(text, search) as part (part.text + (part.match ? '1' : '0'))}
  {#if part.match}
    <mark class="rounded-sm bg-amber-300/60 text-foreground dark:bg-amber-500/40">{part.text}</mark>
  {:else}
    {part.text}
  {/if}
{/each}
