/**
 * Thin composition root for Knowledge admin UI — tab navigation + slice controllers.
 */
import type { KnowledgeDocument } from '$lib/api/knowledge';
import type { KnowledgeTabId } from '../shared/knowledge-pure';
import {
  createKnowledgePreferences,
  type KnowledgeTabPreferences
} from '$lib/preferences/knowledge-preferences.svelte';
import { createKnowledgeAskModel } from './knowledge-ask.svelte';
import { createKnowledgeBrowseModel } from './knowledge-browse.svelte';
import { createKnowledgeGraphModel } from './knowledge-graph.svelte';
import { createKnowledgeIngestModel } from './knowledge-ingest.svelte';
import { createKnowledgeOptionsModel } from './knowledge-options.svelte';

export function createKnowledgePageController(
  tabPrefs: KnowledgeTabPreferences = createKnowledgePreferences()
) {
  let error = $state<string | null>(null);

  function setError(message: string | null) {
    error = message;
  }

  const options = createKnowledgeOptionsModel({ setError });

  let ingest!: ReturnType<typeof createKnowledgeIngestModel>;
  const browse = createKnowledgeBrowseModel({
    options,
    setError,
    onReingest: (documentId) => ingest.reingestActiveDocument(documentId)
  });

  ingest = createKnowledgeIngestModel({
    options,
    setError,
    onJobTerminal: () => {
      void browse.loadDocuments();
      if (browse.activeDocumentId) {
        void browse.openDocument(browse.activeDocumentId);
      }
      if (ingest.folder.trim()) void ingest.scan();
    }
  });

  const ask = createKnowledgeAskModel({ browse, options, setError });
  // Graph viz. The live SSE subscription is owned HERE (page level), not by
  // KnowledgeGraphPanel, so graph deltas keep accumulating in the model even while the
  // user is on another tab (eval/ingest is where a build is triggered). Otherwise the
  // panel — only mounted on the Graph tab — would miss every delta emitted during a build
  // and you'd only ever see a one-shot export. The panel still owns rendering + initial
  // load() when it mounts. Cheap when idle (one shared SSE connection, data in JS maps).
  const graph = createKnowledgeGraphModel({ setError });

  function setActiveTab(tab: KnowledgeTabId) {
    return tabPrefs.setActiveTab(tab);
  }

  function openAskForDocument(document: KnowledgeDocument) {
    void setActiveTab('ask');
    ask.resetForDocument(document);
  }

  function openBrowseForDocument(documentId: string) {
    void setActiveTab('browse');
    void browse.openDocument(documentId);
  }

  async function bootstrap() {
    await Promise.all([browse.loadDocuments(), ingest.loadJobs(), options.loadOptions()]);
    ask.initRewriteDefault(options.rewriteDefaultOn);
    if (ingest.ownerKind === 'character' && !ingest.ownerId && options.characters[0]) {
      ingest.ownerId = String(options.characters[0].id);
    }
    if (ingest.ownerKind === 'user' && !ingest.ownerId && options.users[0]) {
      ingest.ownerId = String(options.users[0].id);
    }
  }

  function mount() {
    ingest.restoreFolderFromStorage();
    void bootstrap();
    const stopEvents = ingest.connectEvents();
    // Page-level graph SSE subscription (see note at `graph` above): stays connected for
    // the whole Knowledge page so live deltas land regardless of the active tab.
    const stopGraphEvents = graph.connectEvents();
    return () => {
      stopEvents();
      stopGraphEvents();
    };
  }

  return {
    get tabPrefs() {
      return tabPrefs;
    },
    get activeTab() {
      return tabPrefs.activeTab;
    },
    setActiveTab,
    syncActiveTabFromUrl: tabPrefs.syncActiveTabFromUrl,
    get error() {
      return error;
    },
    // L3 (Phase 5e) — exposed so the embedded Eval Batch component can route
    // its own transport / setup errors through the page-level error banner
    // (same surface the other sub-controllers already share via setError).
    setError,
    get options() {
      return options;
    },
    get ingest() {
      return ingest;
    },
    get ask() {
      return ask;
    },
    get browse() {
      return browse;
    },
    get graph() {
      return graph;
    },
    openAskForDocument,
    openBrowseForDocument,
    mount
  };
}

export type KnowledgePageController = ReturnType<typeof createKnowledgePageController>;
