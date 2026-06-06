<script lang="ts">
  import type { KnowledgeDocument } from '$lib/api/knowledge';
  import Button from '$lib/components/ui/button.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import KnowledgeAffectedDocumentsList from '$lib/features/knowledge/browse/KnowledgeAffectedDocumentsList.svelte';
  import {
    KNOWLEDGE_BROWSE_BULK_DIALOG,
    KNOWLEDGE_BROWSE_BULK_DIALOG_AFFECTED_LIST,
    KNOWLEDGE_BROWSE_BULK_DIALOG_BODY
  } from '$lib/features/knowledge/shared/knowledge-ui';

  type Props = {
    open: boolean;
    documents: KnowledgeDocument[];
    removing: boolean;
    onConfirm: () => void | Promise<void>;
  };

  let { open = $bindable(false), documents, removing, onConfirm }: Props = $props();

  const documentCount = $derived(documents.length);
</script>

<Dialog.Root bind:open>
  <Dialog.Content class={KNOWLEDGE_BROWSE_BULK_DIALOG} showCloseButton={!removing}>
    <Dialog.Header>
      <Dialog.Title class="break-words">
        {#if documentCount === 1}
          Remove ({documents[0]?.title ?? 'unknown'}) from the knowledge graph?
        {:else}
          Remove {documentCount} documents from the knowledge graph?
        {/if}
      </Dialog.Title>
      <Dialog.Description>
        This deletes the entities and relations extracted from
        {documentCount === 1 ? 'this document' : 'these documents'}. The document
        {documentCount === 1 ? 'entry' : 'entries'} and indexed chunks are kept — you can rebuild the
        graph later from the Add tab.
      </Dialog.Description>
    </Dialog.Header>

    <div class={KNOWLEDGE_BROWSE_BULK_DIALOG_BODY}>
      <KnowledgeAffectedDocumentsList {documents} class={KNOWLEDGE_BROWSE_BULK_DIALOG_AFFECTED_LIST} />
    </div>

    <Dialog.Footer>
      <Button variant="outline" disabled={removing} onclick={() => (open = false)}>Cancel</Button>
      <Button variant="destructive" disabled={removing} onclick={() => void onConfirm()}>
        {#if removing}
          Removing…
        {:else}
          {documentCount === 1 ? 'Remove from graph' : `Remove ${documentCount} from graph`}
        {/if}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
