import type { KnowledgeDocument, KnowledgeScannedFile } from '$lib/api/knowledge';
import type { KnowledgePageController } from '$lib/features/knowledge/state/knowledge-controller.svelte';
import { documentToPreviewFile } from '$lib/features/knowledge/shared/knowledge-pure';
import type { ToastKind } from '$lib/ui/toast-types';
import {
  knowledgeDeleteSuccessMessage,
  knowledgeMetadataSavedMessage
} from './knowledge-browse-messages';

type Notify = (kind: ToastKind, message: string) => void;

export function createKnowledgeBrowsePanelUi(deps: { ctl: KnowledgePageController; notify: Notify }) {
  let previewOpen = $state(false);
  let previewFile = $state<KnowledgeScannedFile | null>(null);
  let deleteOpen = $state(false);
  let deleteTargets = $state<KnowledgeDocument[]>([]);
  let deleting = $state(false);
  let editOpen = $state(false);
  let editTargets = $state<KnowledgeDocument[]>([]);
  let reingestOpen = $state(false);
  let reingestTargets = $state<KnowledgeDocument[]>([]);
  let chunksOpen = $state(false);

  const hasSelection = $derived(deps.ctl.browse.selectedDocumentCount > 0);
  const selectionLabel = $derived(
    deps.ctl.browse.selectedDocumentCount === 1
      ? '1 document selected'
      : `${deps.ctl.browse.selectedDocumentCount} documents selected`
  );

  function snapshotSelectedDocuments(): KnowledgeDocument[] {
    return [...deps.ctl.browse.selectedDocumentRows];
  }

  function openDeleteDialog() {
    deleteTargets = snapshotSelectedDocuments();
    deleteOpen = true;
  }

  function openEditDialog() {
    editTargets = snapshotSelectedDocuments();
    editOpen = true;
  }

  function openReingestDialog() {
    reingestTargets = snapshotSelectedDocuments();
    reingestOpen = true;
  }

  function openDocumentPreview(doc: (typeof deps.ctl.browse.sortedDocuments)[number]) {
    previewFile = documentToPreviewFile(doc);
    previewOpen = true;
  }

  async function openChunksDialog(doc: KnowledgeDocument) {
    await deps.ctl.browse.openDocument(doc.id);
    chunksOpen = true;
  }

  async function confirmDeleteDocuments() {
    if (deleteTargets.length === 0) return;
    deleting = true;
    const result = await deps.ctl.browse.deleteDocuments(deleteTargets.map((document) => document.id));
    deleting = false;
    if (result.deleted > 0) {
      deleteOpen = false;
      deps.notify(
        'success',
        knowledgeDeleteSuccessMessage(result.deleted, result.failed, deleteTargets[0]?.title)
      );
    }
  }

  function handleMetadataSaved(result: { saved: number; failed: number }) {
    deps.notify('success', knowledgeMetadataSavedMessage(result.saved, result.failed));
  }

  function handleAskForDocument(document: KnowledgeDocument) {
    chunksOpen = false;
    deps.ctl.openAskForDocument(document);
  }

  $effect(() => {
    if (!deleteOpen) deleteTargets = [];
  });

  $effect(() => {
    if (!editOpen) editTargets = [];
  });

  $effect(() => {
    if (!reingestOpen) reingestTargets = [];
  });

  return {
    get previewOpen() {
      return previewOpen;
    },
    set previewOpen(value: boolean) {
      previewOpen = value;
    },
    get previewFile() {
      return previewFile;
    },
    get deleteOpen() {
      return deleteOpen;
    },
    set deleteOpen(value: boolean) {
      deleteOpen = value;
    },
    get deleteTargets() {
      return deleteTargets;
    },
    get deleting() {
      return deleting;
    },
    get editOpen() {
      return editOpen;
    },
    set editOpen(value: boolean) {
      editOpen = value;
    },
    get editTargets() {
      return editTargets;
    },
    get reingestOpen() {
      return reingestOpen;
    },
    set reingestOpen(value: boolean) {
      reingestOpen = value;
    },
    get reingestTargets() {
      return reingestTargets;
    },
    get chunksOpen() {
      return chunksOpen;
    },
    set chunksOpen(value: boolean) {
      chunksOpen = value;
    },
    get hasSelection() {
      return hasSelection;
    },
    get selectionLabel() {
      return selectionLabel;
    },
    openDeleteDialog,
    openEditDialog,
    openReingestDialog,
    openDocumentPreview,
    openChunksDialog,
    confirmDeleteDocuments,
    handleMetadataSaved,
    handleAskForDocument
  };
}

export type KnowledgeBrowsePanelUi = ReturnType<typeof createKnowledgeBrowsePanelUi>;
