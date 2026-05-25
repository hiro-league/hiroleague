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
    deleting: boolean;
    onConfirm: () => void | Promise<void>;
  };

  let { open = $bindable(false), documents, deleting, onConfirm }: Props = $props();

  const documentCount = $derived(documents.length);
</script>

<Dialog.Root bind:open>
  <Dialog.Content class={KNOWLEDGE_BROWSE_BULK_DIALOG} showCloseButton={!deleting}>
    <Dialog.Header>
      <Dialog.Title class="break-words">
        {#if documentCount === 1}
          Delete document entry ({documents[0]?.title ?? 'unknown'})?
        {:else}
          Delete {documentCount} document entries?
        {/if}
      </Dialog.Title>
      <Dialog.Description>
        This removes the document {documentCount === 1 ? 'entry' : 'entries'} and all indexed chunks from the
        knowledge base. Source {documentCount === 1 ? 'file' : 'files'} on disk
        {documentCount === 1 ? 'is' : 'are'} not deleted.
      </Dialog.Description>
    </Dialog.Header>

    <div class={KNOWLEDGE_BROWSE_BULK_DIALOG_BODY}>
      <KnowledgeAffectedDocumentsList {documents} class={KNOWLEDGE_BROWSE_BULK_DIALOG_AFFECTED_LIST} />
    </div>

    <Dialog.Footer>
      <Button variant="outline" disabled={deleting} onclick={() => (open = false)}>Cancel</Button>
      <Button variant="destructive" disabled={deleting} onclick={() => void onConfirm()}>
        {documentCount === 1 ? 'Delete Document' : `Delete ${documentCount} Documents`}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
