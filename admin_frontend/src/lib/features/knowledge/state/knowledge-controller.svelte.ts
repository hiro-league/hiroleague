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
    return () => {
      stopEvents();
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
    openAskForDocument,
    openBrowseForDocument,
    mount
  };
}

export type KnowledgePageController = ReturnType<typeof createKnowledgePageController>;
