<script lang="ts">
  import type { Snippet } from 'svelte';
  import Button from '$lib/components/ui/button.svelte';
  import * as Dialog from '$lib/components/ui/dialog';

  // Shared Dialog.Root → Content → Header (title + actions) → body → Footer scaffold for
  // both ingest and retrieval trace dialogs. Callers supply snippets for the parts that differ.
  let {
    open,
    onClose,
    title,
    contentClass = '',
    headActions,
    headerDetail,
    children
  }: {
    open: boolean;
    onClose: () => void;
    title: string;
    /** Extra class(es) on Dialog.Content (e.g. ingest-trace-content / retrieval-trace-content). */
    contentClass?: string;
    /** Everything after Dialog.Title in the header row (nav, search, bulk actions, …). */
    headActions?: Snippet;
    /** Optional block below the title row — Dialog.Description, TraceAnswers, config line, … */
    headerDetail?: Snippet;
    children?: Snippet;
  } = $props();
</script>

<Dialog.Root {open} onOpenChange={(next) => { if (!next) onClose(); }}>
  <Dialog.Content class="{contentClass} sm:max-w-[min(96vw,1200px)] flex flex-col h-[90vh]">
    <Dialog.Header>
      <div class="trace-head-row">
        <Dialog.Title>{title}</Dialog.Title>
        {#if headActions}
          {@render headActions()}
        {/if}
      </div>
      {#if headerDetail}
        {@render headerDetail()}
      {/if}
    </Dialog.Header>

    {#if children}
      {@render children()}
    {/if}

    <Dialog.Footer>
      <Button variant="outline" onclick={onClose}>Close</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<style>
  .trace-head-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding-right: 2.25rem;
  }
</style>
