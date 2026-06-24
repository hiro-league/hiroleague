import {
  deleteKnowledgeDocument,
  getKnowledgeDocument,
  listKnowledgeDocuments,
  updateKnowledgeDocumentMetadata,
  type KnowledgeChunk,
  type KnowledgeDocument,
  type KnowledgeIngestMetadata,
  type KnowledgeJobData
} from '$lib/api/knowledge';
import {
  DEFAULT_DOCUMENT_SORT,
  DOCUMENT_SORT_COLUMNS,
  KNOWLEDGE_CHUNK_FETCH_SIZE,
  KNOWLEDGE_CHUNK_PAGE_SIZE,
  optionalInt,
  sortDocuments,
  KNOWLEDGE_BROWSE_FILTER_KEYS,
  type DocumentSortColumn
} from '../shared/knowledge-pure';
import { useTableSort } from '$lib/components/page/table/use-table-sort.svelte';
import { useTableFilters } from '$lib/components/page/table/use-table-filters.svelte';
import { asTableSortDirection } from '$lib/components/page/table/table-sort-utils';
import type { KnowledgeOptionsModel } from './knowledge-options.svelte';

function tagsFromChunks(chunks: KnowledgeChunk[]): string[] {
  const tags = new Set<string>();
  for (const chunk of chunks) {
    if (!Array.isArray(chunk.tags)) continue;
    for (const tag of chunk.tags as string[]) {
      const clean = tag.trim();
      if (clean) tags.add(clean);
    }
  }
  return [...tags];
}

/** Browse tab: document list, filters, and detail/chunk editor. */
export function createKnowledgeBrowseModel(deps: {
  options: KnowledgeOptionsModel;
  setError: (message: string | null) => void;
  onReingest: (documentId: string) => Promise<void | KnowledgeJobData | null>;
}) {
  const tableFilters = useTableFilters({
    keys: KNOWLEDGE_BROWSE_FILTER_KEYS,
    urlSync: true
  });
  let detailTags = $state<string[]>([]);
  let loadingDocs = $state(false);
  let documents = $state<KnowledgeDocument[]>([]);
  let documentTotal = $state(0);
  let activeDocumentId = $state<string | null>(null);
  let activeDocument = $state<KnowledgeDocument | null>(null);
  let chunks = $state<KnowledgeChunk[]>([]);
  let chunkHasMore = $state(false);
  let chunkNextOffset = $state<string | null>(null);
  let loadingMoreChunks = $state(false);
  let selectedDocuments = $state<Record<string, boolean>>({});
  let filterDebounceTimer: ReturnType<typeof setTimeout> | undefined;

  const documentSort = useTableSort<DocumentSortColumn>({
    defaultBy: DEFAULT_DOCUMENT_SORT.column,
    defaultDirection: DEFAULT_DOCUMENT_SORT.direction,
    allowed: DOCUMENT_SORT_COLUMNS
  });

  const sortedDocuments = $derived(
    sortDocuments(
      documents,
      documentSort.sortBy,
      asTableSortDirection(documentSort.direction),
      deps.options.categoryLabel
    )
  );

  const allDocumentsSelected = $derived(
    sortedDocuments.length > 0 && sortedDocuments.every((doc) => selectedDocuments[doc.id])
  );
  const someDocumentsSelected = $derived(
    sortedDocuments.some((doc) => selectedDocuments[doc.id]) && !allDocumentsSelected
  );
  const selectedDocumentCount = $derived(
    Object.entries(selectedDocuments).filter(([, selected]) => selected).length
  );
  const selectedDocumentRows = $derived(documents.filter((doc) => selectedDocuments[doc.id]));

  const browseSubcategories = $derived(
    deps.options.categories.filter(
      (category) => category.parent_id === optionalInt(tableFilters.filters.kb_category)
    )
  );
  const activeDocumentSubcategories = $derived.by(() => {
    const doc = activeDocument;
    if (!doc) return [];
    return deps.options.categories.filter((category) => category.parent_id === doc.category_id);
  });

  function pruneDocumentSelection() {
    const visibleIds = new Set(documents.map((doc) => doc.id));
    const next: Record<string, boolean> = {};
    for (const [id, selected] of Object.entries(selectedDocuments)) {
      if (selected && visibleIds.has(id)) {
        next[id] = true;
      }
    }
    selectedDocuments = next;
  }

  function toggleDocumentSelection(documentId: string, checked: boolean) {
    selectedDocuments = { ...selectedDocuments, [documentId]: checked };
  }

  function selectAllDocuments() {
    selectedDocuments = Object.fromEntries(sortedDocuments.map((doc) => [doc.id, true]));
  }

  function deselectAllDocuments() {
    selectedDocuments = {};
  }

  function toggleSelectAllDocuments(event: Event) {
    const checked = (event.currentTarget as HTMLInputElement).checked;
    if (checked) selectAllDocuments();
    else deselectAllDocuments();
  }

  function setBrowseFilter(key: (typeof KNOWLEDGE_BROWSE_FILTER_KEYS)[number], value: string) {
    tableFilters.set(key, value);
    queueLoadDocuments();
  }

  function queueLoadDocuments() {
    if (filterDebounceTimer) clearTimeout(filterDebounceTimer);
    filterDebounceTimer = setTimeout(() => {
      filterDebounceTimer = undefined;
      void loadDocuments();
    }, 300);
  }

  function updateActiveDocumentDraft(patch: Partial<KnowledgeDocument>) {
    if (!activeDocument) return;
    activeDocument = { ...activeDocument, ...patch };
  }

  function handleBrowseOwnerKindChange() {
    const kind = tableFilters.filters.kb_owner_kind;
    if (!kind) {
      setBrowseFilter('kb_owner_id', '');
    } else if (kind === 'system') {
      setBrowseFilter('kb_owner_id', '0');
    } else if (kind === 'character') {
      setBrowseFilter('kb_owner_id', String(deps.options.characters[0]?.id ?? ''));
    } else {
      setBrowseFilter('kb_owner_id', String(deps.options.users[0]?.id ?? ''));
    }
  }

  function handleDetailOwnerKindChange() {
    if (!activeDocument) return;
    if (activeDocument.owner_kind === 'system') {
      updateActiveDocumentDraft({ owner_id: '0' });
    } else if (activeDocument.owner_kind === 'character') {
      updateActiveDocumentDraft({ owner_id: String(deps.options.characters[0]?.id ?? '') });
    } else {
      updateActiveDocumentDraft({ owner_id: String(deps.options.users[0]?.id ?? '') });
    }
  }

  function clearBrowseFilters() {
    if (filterDebounceTimer) {
      clearTimeout(filterDebounceTimer);
      filterDebounceTimer = undefined;
    }
    tableFilters.reset();
    void loadDocuments();
  }

  const hasBrowseFilters = $derived(
    Object.values(tableFilters.filters).some((v) => v.trim() !== '')
  );

  async function loadDocuments() {
    loadingDocs = true;
    const f = tableFilters.filters;
    try {
      const payload = await listKnowledgeDocuments({
        status: f.kb_status,
        owner_kind: f.kb_owner_kind || undefined,
        owner_id: f.kb_owner_kind ? f.kb_owner_id : undefined,
        category_id: optionalInt(f.kb_category),
        subcategory_id: optionalInt(f.kb_subcategory),
        tag: f.kb_tag || undefined,
        title: f.kb_title,
        limit: 100
      });
      documents = payload.data.documents;
      documentTotal = payload.data.total;
      pruneDocumentSelection();
      if (!activeDocumentId && documents[0]) {
        await openDocument(documents[0].id);
      } else if (activeDocumentId && !activeDocument) {
        await openDocument(activeDocumentId);
      }
    } catch (err) {
      deps.setError(err instanceof Error ? err.message : 'Could not load documents.');
    } finally {
      loadingDocs = false;
    }
  }

  function applyFetchedChunks(fetched: KnowledgeChunk[], nextOffset: string | null | undefined, append: boolean) {
    if (fetched.length > KNOWLEDGE_CHUNK_PAGE_SIZE) {
      const page = fetched.slice(0, KNOWLEDGE_CHUNK_PAGE_SIZE);
      chunks = append ? [...chunks, ...page] : page;
      chunkHasMore = true;
      chunkNextOffset = nextOffset ?? null;
      return;
    }
    chunks = append ? [...chunks, ...fetched] : fetched;
    chunkHasMore = false;
    chunkNextOffset = null;
  }

  async function openDocument(documentId: string) {
    activeDocumentId = documentId;
    chunkHasMore = false;
    chunkNextOffset = null;
    try {
      const payload = await getKnowledgeDocument(documentId, { chunkLimit: KNOWLEDGE_CHUNK_FETCH_SIZE });
      activeDocument = payload.data.document;
      applyFetchedChunks(payload.data.chunks, payload.data.chunk_next_offset, false);
      const apiTags = payload.data.document?.tags ?? [];
      const chunkTags = tagsFromChunks(payload.data.chunks);
      const listTags = documents.find((document) => document.id === documentId)?.tags ?? [];
      detailTags = [...(apiTags.length > 0 ? apiTags : chunkTags.length > 0 ? chunkTags : listTags)];
    } catch (err) {
      deps.setError(err instanceof Error ? err.message : 'Could not load document.');
    }
  }

  async function loadMoreChunks() {
    if (!activeDocumentId || !chunkHasMore || loadingMoreChunks) return;
    loadingMoreChunks = true;
    try {
      const payload = await getKnowledgeDocument(activeDocumentId, {
        chunkLimit: KNOWLEDGE_CHUNK_FETCH_SIZE,
        chunkOffset: chunkNextOffset
      });
      applyFetchedChunks(payload.data.chunks, payload.data.chunk_next_offset, true);
    } catch (err) {
      deps.setError(err instanceof Error ? err.message : 'Could not load more chunks.');
    } finally {
      loadingMoreChunks = false;
    }
  }

  async function deleteDocuments(documentIds: string[]): Promise<{ deleted: number; failed: number }> {
    if (documentIds.length === 0) return { deleted: 0, failed: 0 };
    deps.setError(null);
    let deleted = 0;
    let failed = 0;
    for (const documentId of documentIds) {
      try {
        await deleteKnowledgeDocument(documentId);
        deleted++;
        if (selectedDocuments[documentId]) {
          const next = { ...selectedDocuments };
          delete next[documentId];
          selectedDocuments = next;
        }
        if (activeDocumentId === documentId) {
          activeDocumentId = null;
          activeDocument = null;
          chunks = [];
          chunkHasMore = false;
          chunkNextOffset = null;
          detailTags = [];
        }
      } catch (err) {
        failed++;
        deps.setError(err instanceof Error ? err.message : 'Delete failed.');
      }
    }
    if (deleted > 0) {
      await loadDocuments();
    }
    return { deleted, failed };
  }

  async function deleteDocument(documentId: string) {
    if (!documentId) return false;
    const result = await deleteDocuments([documentId]);
    return result.deleted === 1;
  }

  async function reingestActiveDocument() {
    if (!activeDocumentId) return;
    await deps.onReingest(activeDocumentId);
  }

  async function saveActiveMetadata() {
    if (!activeDocument) return false;
    return saveDocumentMetadata(activeDocument.id, {
      owner_kind: activeDocument.owner_kind as KnowledgeIngestMetadata['owner_kind'],
      owner_id: activeDocument.owner_id,
      category_id: activeDocument.category_id,
      subcategory_id: activeDocument.subcategory_id,
      tags: detailTags
    });
  }

  async function saveDocumentsMetadata(
    documentIds: string[],
    metadata: KnowledgeIngestMetadata
  ): Promise<{ saved: number; failed: number }> {
    if (documentIds.length === 0) return { saved: 0, failed: 0 };
    deps.setError(null);
    let saved = 0;
    let failed = 0;
    for (const documentId of documentIds) {
      try {
        await updateKnowledgeDocumentMetadata(documentId, metadata);
        saved++;
      } catch (err) {
        failed++;
        deps.setError(err instanceof Error ? err.message : 'Metadata update failed.');
      }
    }
    if (saved > 0) {
      await loadDocuments();
      if (activeDocumentId && documentIds.includes(activeDocumentId)) {
        await openDocument(activeDocumentId);
      }
    }
    return { saved, failed };
  }

  async function saveDocumentMetadata(
    documentId: string,
    metadata: KnowledgeIngestMetadata
  ): Promise<boolean> {
    const result = await saveDocumentsMetadata([documentId], metadata);
    return result.saved === 1;
  }

  return {
    get browseStatus() {
      return tableFilters.filters.kb_status;
    },
    set browseStatus(v: string) {
      setBrowseFilter('kb_status', v);
    },
    get browseOwnerKind() {
      return tableFilters.filters.kb_owner_kind;
    },
    set browseOwnerKind(v: string) {
      tableFilters.set('kb_owner_kind', v);
    },
    get browseOwnerId() {
      return tableFilters.filters.kb_owner_id;
    },
    set browseOwnerId(v: string) {
      setBrowseFilter('kb_owner_id', v);
    },
    get browseCategoryId() {
      return tableFilters.filters.kb_category;
    },
    set browseCategoryId(v: string) {
      setBrowseFilter('kb_category', v);
    },
    get browseSubcategoryId() {
      return tableFilters.filters.kb_subcategory;
    },
    set browseSubcategoryId(v: string) {
      setBrowseFilter('kb_subcategory', v);
    },
    get browseTags() {
      const tag = tableFilters.filters.kb_tag.trim();
      return tag ? [tag] : [];
    },
    set browseTags(v: string[]) {
      setBrowseFilter('kb_tag', v[0] ?? '');
    },
    get browseTitle() {
      return tableFilters.filters.kb_title;
    },
    set browseTitle(v: string) {
      setBrowseFilter('kb_title', v);
    },
    get detailTags() {
      return detailTags;
    },
    set detailTags(v: string[]) {
      detailTags = v;
    },
    get detailCategoryId() {
      return activeDocument?.category_id != null ? String(activeDocument.category_id) : '';
    },
    set detailCategoryId(v: string) {
      updateActiveDocumentDraft({ category_id: optionalInt(v), subcategory_id: null });
    },
    get detailSubcategoryId() {
      return activeDocument?.subcategory_id != null ? String(activeDocument.subcategory_id) : '';
    },
    set detailSubcategoryId(v: string) {
      updateActiveDocumentDraft({ subcategory_id: optionalInt(v) });
    },
    get loadingDocs() {
      return loadingDocs;
    },
    get documents() {
      return documents;
    },
    get sortedDocuments() {
      return sortedDocuments;
    },
    get selectedDocuments() {
      return selectedDocuments;
    },
    get allDocumentsSelected() {
      return allDocumentsSelected;
    },
    get someDocumentsSelected() {
      return someDocumentsSelected;
    },
    get selectedDocumentCount() {
      return selectedDocumentCount;
    },
    get selectedDocumentRows() {
      return selectedDocumentRows;
    },
    get documentSort() {
      return documentSort;
    },
    get documentTotal() {
      return documentTotal;
    },
    get activeDocumentId() {
      return activeDocumentId;
    },
    get chunks() {
      return chunks;
    },
    get chunkHasMore() {
      return chunkHasMore;
    },
    get loadingMoreChunks() {
      return loadingMoreChunks;
    },
    get activeDocument() {
      return activeDocument;
    },
    get browseSubcategories() {
      return browseSubcategories;
    },
    get activeDocumentSubcategories() {
      return activeDocumentSubcategories;
    },
    get hasBrowseFilters() {
      return hasBrowseFilters;
    },
    loadDocuments,
    clearBrowseFilters,
    queueLoadDocuments,
    handleBrowseOwnerKindChange,
    handleDetailOwnerKindChange,
    toggleDocumentSelection,
    toggleSelectAllDocuments,
    openDocument,
    loadMoreChunks,
    deleteDocument,
    deleteDocuments,
    reingestActiveDocument,
    saveActiveMetadata,
    saveDocumentMetadata,
    saveDocumentsMetadata,
    updateActiveDocumentDraft
  };
}

export type KnowledgeBrowseModel = ReturnType<typeof createKnowledgeBrowseModel>;
