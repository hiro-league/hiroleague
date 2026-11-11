<script lang="ts">
  import { untrack } from 'svelte';
  import StickyBar from '$kit/ui/sticky-bar.svelte';
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
  import { toast } from '$kit/ui/toast.svelte';

  interface Props {
    ctl: KnowledgePageController;
  }

  let { ctl }: Props = $props();

  const ui = untrack(() => createKnowledgeBrowsePanelUi({ ctl, notify: toast.show }));
</script>

<section class="grid gap-4">
  <StickyBar class="-mx-4 border-b bg-background/85 px-4 backdrop-blur md:-mx-6 md:px-6">
    <KnowledgeBrowseFilterBar browse={ctl.browse} options={ctl.options} />
  </StickyBar>

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
  open={ui.deleteOpen}
  onOpenChange={(next) => (ui.deleteOpen = next)}
  documents={ui.deleteTargets}
  deleting={ui.deleting}
  onConfirm={ui.confirmDeleteDocuments}
/>

<KnowledgeBrowseRemoveGraphDialog
  open={ui.removeGraphOpen}
  onOpenChange={(next) => (ui.removeGraphOpen = next)}
  documents={ui.removeGraphTargets}
  removing={ui.removingGraph}
  onConfirm={ui.confirmRemoveFromGraph}
/>

