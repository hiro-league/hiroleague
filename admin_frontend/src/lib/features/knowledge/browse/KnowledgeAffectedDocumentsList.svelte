<script lang="ts">
  import type { KnowledgeDocument } from '$lib/api/knowledge';
  import { fileName } from '$lib/features/knowledge/shared/knowledge-pure';
  import { cn } from '$lib/utils';

  type Props = {
    documents: KnowledgeDocument[];
    class?: string;
  };

  let { documents, class: className }: Props = $props();
</script>

{#if documents.length > 0}
  <ul
    class={cn(
      'max-h-40 list-disc space-y-1.5 overflow-y-auto pl-5 font-sans text-sm text-foreground',
      className
    )}
  >
    {#each documents as document (document.id)}
      <li class="break-words">
        <span class="font-medium">{document.title}</span>
        <span class="mx-1.5 select-none text-border" aria-hidden="true">·</span>
        <span class="font-mono text-xs text-muted-foreground">{fileName(document.source_uri)}</span>
      </li>
    {/each}
  </ul>
{/if}
