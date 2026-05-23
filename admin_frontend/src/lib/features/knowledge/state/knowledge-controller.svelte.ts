/**
 * Thin composition root for Knowledge admin UI — tab navigation + slice controllers.
 */
import { page } from '$app/state';
import type { KnowledgeDocument } from '$lib/api/knowledge';
import type { KnowledgeTabId } from '../shared/knowledge-pure';
import { readKnowledgeTabFromLocation, persistKnowledgeTabToUrl } from '../shared/knowledge-nav';
import { createKnowledgeAskModel } from './knowledge-ask.svelte';
import { createKnowledgeBrowseModel } from './knowledge-browse.svelte';
import { createKnowledgeIngestModel } from './knowledge-ingest.svelte';
import { createKnowledgeOptionsModel } from './knowledge-options.svelte';

export function createKnowledgePageController() {
  let activeTab = $state<KnowledgeTabId>('ingest');
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
      if (ingest.folder.trim()) void ingest.scan();
    }
  });

  const ask = createKnowledgeAskModel({ browse, options, setError });

  function initializeNavigation() {
    activeTab = readKnowledgeTabFromLocation(page.url.searchParams);
  }

  async function syncUrl() {
    await persistKnowledgeTabToUrl(page.url, activeTab);
  }

  async function setActiveTab(tab: KnowledgeTabId) {
    activeTab = tab;
    await syncUrl();
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
    if (ingest.ownerKind === 'character' && !ingest.ownerId && options.characters[0]) {
      ingest.ownerId = String(options.characters[0].id);
    }
    if (ingest.ownerKind === 'user' && !ingest.ownerId && options.users[0]) {
      ingest.ownerId = String(options.users[0].id);
    }
  }

  function mount() {
    initializeNavigation();
    ingest.restoreFolderFromStorage();
    void bootstrap();
    void syncUrl();
    const stopEvents = ingest.connectEvents();
    return () => {
      stopEvents();
    };
  }

  return {
    get activeTab() {
      return activeTab;
    },
    setActiveTab,
    get error() {
      return error;
    },
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
