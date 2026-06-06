import type { KnowledgeDocument, KnowledgeScannedFile } from '$lib/api/knowledge';
import { removeDocumentFromKnowledgeGraph } from '$lib/api/knowledge';
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
  let removeGraphOpen = $state(false);
  let removeGraphTargets = $state<KnowledgeDocument[]>([]);
  let removingGraph = $state(false);
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

  function openRemoveGraphDialog() {
    removeGraphTargets = snapshotSelectedDocuments();
    removeGraphOpen = true;
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

  async function confirmRemoveFromGraph() {
    if (removeGraphTargets.length === 0) return;
    removingGraph = true;
    // Per-document isolation (matches the graph-ingest pattern): a failed doc doesn't
    // abort the rest. We call the per-document graph delete for each selected doc.
    let removedEpisodes = 0;
    let failed = 0;
    for (const document of removeGraphTargets) {
      const res = await removeDocumentFromKnowledgeGraph(document.id);
      if (res.ok && res.data) removedEpisodes += res.data.removed_episodes;
      else failed += 1;
    }
    removingGraph = false;
    const docCount = removeGraphTargets.length;
    if (failed === 0) {
      removeGraphOpen = false;
      deps.notify(
        'success',
        `Removed ${docCount} document${docCount === 1 ? '' : 's'} from the knowledge graph` +
          ` (${removedEpisodes} episode${removedEpisodes === 1 ? '' : 's'}).`
      );
    } else {
      deps.notify(
        'error',
        `Removed ${docCount - failed}/${docCount} from the graph — ${failed} failed.`
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

  $effect(() => {
    if (!removeGraphOpen) removeGraphTargets = [];
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
    get removeGraphOpen() {
      return removeGraphOpen;
    },
    set removeGraphOpen(value: boolean) {
      removeGraphOpen = value;
    },
    get removeGraphTargets() {
      return removeGraphTargets;
    },
    get removingGraph() {
      return removingGraph;
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
    openRemoveGraphDialog,
    openDocumentPreview,
    openChunksDialog,
    confirmDeleteDocuments,
    confirmRemoveFromGraph,
    handleMetadataSaved,
    handleAskForDocument
  };
}

export type KnowledgeBrowsePanelUi = ReturnType<typeof createKnowledgeBrowsePanelUi>;
