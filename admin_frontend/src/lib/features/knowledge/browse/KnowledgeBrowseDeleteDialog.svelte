<script lang="ts">
  import type { KnowledgeDocument } from '$lib/api/knowledge';
  import ConfirmDialog from '$lib/components/ui/dialog/ConfirmDialog.svelte';
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
    onOpenChange: (open: boolean) => void; // required — forwarded to ConfirmDialog's dismissal handler
    onConfirm: () => void | Promise<void>;
  };

  let { open, documents, deleting, onOpenChange, onConfirm }: Props = $props();

  const documentCount = $derived(documents.length);
  const title = $derived(
    documentCount === 1
      ? `Delete document entry (${documents[0]?.title ?? 'unknown'})?`
      : `Delete ${documentCount} document entries?`
  );
  const message = $derived(
    `This removes the document ${documentCount === 1 ? 'entry' : 'entries'} and all indexed chunks from the knowledge base. Source ${documentCount === 1 ? 'file' : 'files'} on disk ${documentCount === 1 ? 'is' : 'are'} not deleted.`
  );
  const confirmLabel = $derived(
    documentCount === 1 ? 'Delete Document' : `Delete ${documentCount} Documents`
  );
</script>

<ConfirmDialog
  {open}
  {onOpenChange}
  {title}
  {message}
  {confirmLabel}
  pending={deleting}
  disableCancelWhenPending={true}
  widthClass={KNOWLEDGE_BROWSE_BULK_DIALOG}
  showCloseButton={!deleting}
  {onConfirm}
>
  {#snippet children()}
    <div class={KNOWLEDGE_BROWSE_BULK_DIALOG_BODY}>
      <KnowledgeAffectedDocumentsList {documents} class={KNOWLEDGE_BROWSE_BULK_DIALOG_AFFECTED_LIST} />
    </div>
  {/snippet}
</ConfirmDialog>
