<script lang="ts">
  import { untrack } from 'svelte';
  import AdminPageStickyToolbar from '$lib/components/page/AdminPageStickyToolbar.svelte';
  import KnowledgeBrowseDeleteDialog from '$lib/features/knowledge/browse/KnowledgeBrowseDeleteDialog.svelte';
  import KnowledgeBrowseRemoveGraphDialog from '$lib/features/knowledge/browse/KnowledgeBrowseRemoveGraphDialog.svelte';
  import KnowledgeBrowseDocumentListSection from '$lib/features/knowledge/browse/KnowledgeBrowseDocumentListSection.svelte';
  import KnowledgeBrowseFilterBar from '$lib/features/knowledge/browse/KnowledgeBrowseFilterBar.svelte';
  import { createKnowledgeBrowsePanelUi } from '$lib/features/knowledge/browse/knowledge-browse-panel.svelte';
  import KnowledgeDocumentChunksDialog from '$lib/features/knowledge/browse/KnowledgeDocumentChunksDialog.svelte';
  import KnowledgeDocumentMetadataDialog from '$lib/features/knowledge/browse/KnowledgeDocumentMetadataDialog.svelte';
  import KnowledgeDocumentReingestDialog from '$lib/features/knowledge/browse/KnowledgeDocumentReingestDialog.svelte';
  import KnowledgeFilePreviewDialog from '$lib/features/knowledge/shared/file-preview/KnowledgeFilePreviewDialog.svelte';
  import type { KnowledgePageController } from '$lib/features/knowledge/state/knowledge-controller.svelte';
  import { createToastNotifier } from '$lib/ui/create-toast-notifier.svelte';
  import ToastHost from '$lib/ui/ToastHost.svelte';

  interface Props {
    ctl: KnowledgePageController;
  }

  let { ctl }: Props = $props();

  const toasts = createToastNotifier();
  const ui = untrack(() => createKnowledgeBrowsePanelUi({ ctl, notify: toasts.notify }));
</script>

<section class="grid gap-4">
  <AdminPageStickyToolbar>
    <KnowledgeBrowseFilterBar browse={ctl.browse} options={ctl.options} />
  </AdminPageStickyToolbar>

  <KnowledgeBrowseDocumentListSection
    browse={ctl.browse}
    options={ctl.options}
    hasSelection={ui.hasSelection}
    selectionLabel={ui.selectionLabel}
    onUpdateMetadata={ui.openEditDialog}
    onReingest={ui.openReingestDialog}
    onDelete={ui.openDeleteDialog}
    onRemoveFromGraph={ui.openRemoveGraphDialog}
    onPreview={ui.openDocumentPreview}
    onOpenChunks={ui.openChunksDialog}
  />
</section>

<KnowledgeFilePreviewDialog bind:open={ui.previewOpen} file={ui.previewFile} />

<KnowledgeDocumentChunksDialog
  bind:open={ui.chunksOpen}
  browse={ctl.browse}
  options={ctl.options}
  onAskForDocument={ui.handleAskForDocument}
/>

<KnowledgeDocumentMetadataDialog
  bind:open={ui.editOpen}
  documents={ui.editTargets}
  browse={ctl.browse}
  options={ctl.options}
  onSaved={ui.handleMetadataSaved}
/>

<KnowledgeDocumentReingestDialog bind:open={ui.reingestOpen} documents={ui.reingestTargets} ingest={ctl.ingest} />

<KnowledgeBrowseDeleteDialog
  bind:open={ui.deleteOpen}
  documents={ui.deleteTargets}
  deleting={ui.deleting}
  onConfirm={ui.confirmDeleteDocuments}
/>

<KnowledgeBrowseRemoveGraphDialog
  bind:open={ui.removeGraphOpen}
  documents={ui.removeGraphTargets}
  removing={ui.removingGraph}
  onConfirm={ui.confirmRemoveFromGraph}
/>

<ToastHost toast={toasts.toast} />
