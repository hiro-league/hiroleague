import { answerKnowledge, type KnowledgeAnswerData } from '$lib/api/knowledge';
import { buildAskFilters, optionalInt } from '../shared/knowledge-pure';
import type { KnowledgeBrowseModel } from './knowledge-browse.svelte';
import type { KnowledgeOptionsModel } from './knowledge-options.svelte';

/** Ask tab: query, filters, and answer results. */
export function createKnowledgeAskModel(deps: {
  browse: KnowledgeBrowseModel;
  options: KnowledgeOptionsModel;
  setError: (message: string | null) => void;
}) {
  let query = $state('');
  let askTopK = $state(20);
  let askMinScore = $state(0);
  let askOwnerKind = $state('');
  let askOwnerId = $state('');
  let askCategoryId = $state('');
  let askSubcategoryId = $state('');
  let askTagsText = $state('');
  let askDocumentId = $state<string | null>(null);
  let queryInputEl = $state<HTMLInputElement | null>(null);
  let searching = $state(false);
  let answerResult = $state<KnowledgeAnswerData | null>(null);

  const askDocumentScope = $derived(
    deps.browse.documents.find((doc) => doc.id === askDocumentId) ?? null
  );
  const askSubcategories = $derived(
    deps.options.categories.filter((category) => category.parent_id === optionalInt(askCategoryId))
  );

  async function runSearch() {
    if (!query.trim()) return;
    searching = true;
    deps.setError(null);
    try {
      const payload = await answerKnowledge(
        query.trim(),
        askTopK,
        askMinScore,
        buildAskFilters({ askOwnerKind, askOwnerId, askCategoryId, askSubcategoryId, askTagsText, askDocumentId })
      );
      answerResult = payload.data;
    } catch (err) {
      deps.setError(err instanceof Error ? err.message : 'Ask failed.');
    } finally {
      searching = false;
    }
  }

  function clearAskDocumentScope() {
    askDocumentId = null;
  }

  function resetForDocument(document: {
    id: string;
    owner_kind: string;
    owner_id: string;
    category_id: number | null;
    subcategory_id: number | null;
  }) {
    askDocumentId = document.id;
    askOwnerKind = document.owner_kind;
    askOwnerId = document.owner_id;
    askCategoryId = document.category_id !== null ? String(document.category_id) : '';
    askSubcategoryId = document.subcategory_id !== null ? String(document.subcategory_id) : '';
    query = '';
    answerResult = null;
    queueMicrotask(() => queryInputEl?.focus());
  }

  return {
    get query() {
      return query;
    },
    set query(v: string) {
      query = v;
    },
    get askTopK() {
      return askTopK;
    },
    set askTopK(v: number) {
      askTopK = v;
    },
    get askMinScore() {
      return askMinScore;
    },
    set askMinScore(v: number) {
      askMinScore = v;
    },
    get askOwnerKind() {
      return askOwnerKind;
    },
    set askOwnerKind(v: string) {
      askOwnerKind = v;
    },
    get askOwnerId() {
      return askOwnerId;
    },
    set askOwnerId(v: string) {
      askOwnerId = v;
    },
    get askCategoryId() {
      return askCategoryId;
    },
    set askCategoryId(v: string) {
      askCategoryId = v;
    },
    get askSubcategoryId() {
      return askSubcategoryId;
    },
    set askSubcategoryId(v: string) {
      askSubcategoryId = v;
    },
    get askTagsText() {
      return askTagsText;
    },
    set askTagsText(v: string) {
      askTagsText = v;
    },
    get queryInputEl() {
      return queryInputEl;
    },
    set queryInputEl(v: HTMLInputElement | null) {
      queryInputEl = v;
    },
    get searching() {
      return searching;
    },
    get answerResult() {
      return answerResult;
    },
    get askDocumentScope() {
      return askDocumentScope;
    },
    get askSubcategories() {
      return askSubcategories;
    },
    runSearch,
    clearAskDocumentScope,
    resetForDocument
  };
}

export type KnowledgeAskModel = ReturnType<typeof createKnowledgeAskModel>;
