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
    removing: boolean;
    onOpenChange: (open: boolean) => void; // required — forwarded to ConfirmDialog's dismissal handler
    onConfirm: () => void | Promise<void>;
  };

  let { open, documents, removing, onOpenChange, onConfirm }: Props = $props();

  const documentCount = $derived(documents.length);
  const title = $derived(
    documentCount === 1
      ? `Remove (${documents[0]?.title ?? 'unknown'}) from the knowledge graph?`
      : `Remove ${documentCount} documents from the knowledge graph?`
  );
  const message = $derived(
    `This deletes the entities and relations extracted from ${documentCount === 1 ? 'this document' : 'these documents'}. The document ${documentCount === 1 ? 'entry' : 'entries'} and indexed chunks are kept — you can rebuild the graph later from the Add tab.`
  );
  const confirmLabel = $derived(
    removing
      ? 'Removing…'
      : documentCount === 1
        ? 'Remove from graph'
        : `Remove ${documentCount} from graph`
  );
</script>

<ConfirmDialog
  {open}
  {onOpenChange}
  {title}
  {message}
  {confirmLabel}
  pending={removing}
  disableCancelWhenPending={true}
  widthClass={KNOWLEDGE_BROWSE_BULK_DIALOG}
  showCloseButton={!removing}
  {onConfirm}
>
  {#snippet children()}
    <div class={KNOWLEDGE_BROWSE_BULK_DIALOG_BODY}>
      <KnowledgeAffectedDocumentsList {documents} class={KNOWLEDGE_BROWSE_BULK_DIALOG_AFFECTED_LIST} />
    </div>
  {/snippet}
</ConfirmDialog>
