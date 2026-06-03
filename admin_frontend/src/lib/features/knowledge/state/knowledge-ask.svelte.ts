import {
  answerKnowledge,
  isAnswerCompareData,
  type KnowledgeAnswerCompareData,
  type KnowledgeAnswerData,
  type KnowledgeGraphMode
} from '$lib/api/knowledge';
import {
  buildAskFilters,
  clearPersistedKnowledgeAskCompareResult,
  clearPersistedKnowledgeAskResult,
  optionalInt,
  readPersistedKnowledgeAskCompareResult,
  readPersistedKnowledgeAskResult,
  readPersistedKnowledgeGraphMode,
  writePersistedKnowledgeAskCompareResult,
  writePersistedKnowledgeAskResult,
  writePersistedKnowledgeGraphMode
} from '../shared/knowledge-pure';
import { untrack } from 'svelte';
import type { KnowledgeBrowseModel } from './knowledge-browse.svelte';
import type { KnowledgeOptionsModel } from './knowledge-options.svelte';

const DEFAULT_ASK_TOP_K = 20;
const DEFAULT_ASK_MIN_SCORE = 0;

/** Ask tab: query, filters, and answer results. */
export function createKnowledgeAskModel(deps: {
  browse: KnowledgeBrowseModel;
  options: KnowledgeOptionsModel;
  setError: (message: string | null) => void;
}) {
  let askTopK = $state(DEFAULT_ASK_TOP_K);
  let askMinScore = $state(DEFAULT_ASK_MIN_SCORE);
  // Opt-in: request per-branch scores + matched terms for human evaluation of results.
  let askExplain = $state(false);
  // Opt-in: LLM query rewrite (normalize + keyword-extract) before retrieval. The workspace
  // default (knowledge.rewrite.default_on) seeds this via initRewriteDefault on first load.
  let rewriteDefault = $state(false);
  let askRewrite = $state(false);
  let askOwnerKind = $state('');
  let askOwnerId = $state('');
  let askCategoryId = $state('');
  let askSubcategoryId = $state('');
  let askTags = $state<string[]>([]);
  let askDocumentId = $state<string | null>(null);
  let queryInputEl = $state<HTMLInputElement | null>(null);
  let searching = $state(false);
  // Restore the last answer cached in sessionStorage so results survive navigating to other admin
  // pages and back (asking costs an LLM call). Seed the query box to match the restored answer.
  let answerResult = $state<KnowledgeAnswerData | null>(readPersistedKnowledgeAskResult());
  // L3 (Phase 5d) — compare-mode cache lives alongside the single-leg cache so
  // toggling between modes doesn't lose the other side's result.
  let compareResult = $state<KnowledgeAnswerCompareData | null>(
    readPersistedKnowledgeAskCompareResult()
  );
  // L3 graph mode: 'off' = today's flat hybrid+rerank, 'on' = graph-augmented
  // (focuses Qdrant on chunks linked to query entities), 'compare' = both legs
  // side-by-side. Persisted across browser sessions so the user's preference
  // sticks. Default 'off' preserves existing behavior.
  let graphMode = $state<KnowledgeGraphMode>(readPersistedKnowledgeGraphMode());
  // Seed the query box from whichever result is "active" given the current mode.
  let query = $state(
    untrack(() =>
      graphMode === 'compare'
        ? (compareResult?.query ?? '')
        : (answerResult?.query ?? '')
    )
  );

  const askDocumentScope = $derived(
    deps.browse.documents.find((doc) => doc.id === askDocumentId) ?? null
  );
  const askSubcategories = $derived(
    deps.options.categories.filter((category) => category.parent_id === optionalInt(askCategoryId))
  );
  const hasAskFilters = $derived(
    askOwnerKind !== '' ||
      askOwnerId !== '' ||
      askCategoryId !== '' ||
      askSubcategoryId !== '' ||
      askTags.length > 0 ||
      askDocumentId !== null ||
      askTopK !== DEFAULT_ASK_TOP_K ||
      askMinScore !== DEFAULT_ASK_MIN_SCORE ||
      askRewrite !== rewriteDefault
  );

  // Seed the Ask-tab toggle from the workspace default once options have loaded.
  function initRewriteDefault(on: boolean) {
    rewriteDefault = on;
    askRewrite = on;
  }

  async function runSearch() {
    if (!query.trim()) return;
    searching = true;
    deps.setError(null);
    try {
      const payload = await answerKnowledge(
        query.trim(),
        askTopK,
        askMinScore,
        buildAskFilters({
          askOwnerKind,
          askOwnerId,
          askCategoryId,
          askSubcategoryId,
          askTags,
          askDocumentId
        }),
        askExplain,
        askRewrite,
        graphMode
      );
      // Server returns one of two shapes depending on graph_mode — use the type
      // guard to populate the right slot. The opposite-slot cache stays so
      // toggling modes doesn't blow away the other view.
      if (isAnswerCompareData(payload.data)) {
        compareResult = payload.data;
        writePersistedKnowledgeAskCompareResult(payload.data);
      } else {
        answerResult = payload.data;
        writePersistedKnowledgeAskResult(payload.data);
      }
    } catch (err) {
      deps.setError(err instanceof Error ? err.message : 'Ask failed.');
    } finally {
      searching = false;
    }
  }

  function setGraphMode(mode: KnowledgeGraphMode) {
    if (mode === graphMode) return;
    graphMode = mode;
    writePersistedKnowledgeGraphMode(mode);
  }

  function handleAskOwnerKindChange() {
    if (!askOwnerKind) {
      askOwnerId = '';
    } else if (askOwnerKind === 'system') {
      askOwnerId = '0';
    } else if (askOwnerKind === 'character') {
      askOwnerId = String(deps.options.characters[0]?.id ?? '');
    } else {
      askOwnerId = String(deps.options.users[0]?.id ?? '');
    }
  }

  function clearAskFilters() {
    askOwnerKind = '';
    askOwnerId = '';
    askCategoryId = '';
    askSubcategoryId = '';
    askTags = [];
    askDocumentId = null;
    askTopK = DEFAULT_ASK_TOP_K;
    askMinScore = DEFAULT_ASK_MIN_SCORE;
    askRewrite = rewriteDefault;
  }

  function clearAskDocumentScope() {
    askDocumentId = null;
  }

  // Explicit "Clear" action: drop BOTH the current answer + compare caches so the
  // next question starts fresh in whichever mode the user is in. (Keeping the other
  // mode's cache around would make "Clear" feel inconsistent.)
  function clearAnswer() {
    answerResult = null;
    compareResult = null;
    clearPersistedKnowledgeAskResult();
    clearPersistedKnowledgeAskCompareResult();
    queueMicrotask(() => queryInputEl?.focus());
  }

  function resetForDocument(document: {
    id: string;
    owner_kind: string;
    owner_id: string;
    category_id: number | null;
    subcategory_id: number | null;
    tags?: string[];
  }) {
    askDocumentId = document.id;
    askOwnerKind = document.owner_kind;
    askOwnerId = document.owner_id;
    askCategoryId = document.category_id !== null ? String(document.category_id) : '';
    askSubcategoryId = document.subcategory_id !== null ? String(document.subcategory_id) : '';
    askTags = [...(document.tags ?? [])];
    query = '';
    answerResult = null;
    compareResult = null;
    clearPersistedKnowledgeAskResult();
    clearPersistedKnowledgeAskCompareResult();
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
    get askExplain() {
      return askExplain;
    },
    set askExplain(v: boolean) {
      askExplain = v;
    },
    get askRewrite() {
      return askRewrite;
    },
    set askRewrite(v: boolean) {
      askRewrite = v;
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
    get askTags() {
      return askTags;
    },
    set askTags(v: string[]) {
      askTags = v;
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
    get compareResult() {
      return compareResult;
    },
    get graphMode() {
      return graphMode;
    },
    setGraphMode,
    get askDocumentScope() {
      return askDocumentScope;
    },
    get askSubcategories() {
      return askSubcategories;
    },
    get hasAskFilters() {
      return hasAskFilters;
    },
    runSearch,
    handleAskOwnerKindChange,
    clearAskFilters,
    clearAskDocumentScope,
    clearAnswer,
    resetForDocument,
    initRewriteDefault
  };
}

export type KnowledgeAskModel = ReturnType<typeof createKnowledgeAskModel>;
