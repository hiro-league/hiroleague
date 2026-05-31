import {
  ingestKnowledge,
  listKnowledgeDocuments,
  listKnowledgeJobs,
  pickKnowledgeFolder,
  reingestKnowledgeDocument,
  runKnowledgeGraphIngestBatch,
  scanKnowledgeFolder,
  type KnowledgeGraphIngestBatchData,
  type KnowledgeIngestMetadata,
  type KnowledgeJobData,
  type KnowledgeJobRecord,
  type KnowledgeScannedFile
} from '$lib/api/knowledge';
import { openWorkspaceFolder } from '$lib/api/server';
import { PREF_KEYS } from '$lib/preferences/keys';
import { readLocalBoolean, writeLocalBoolean } from '$lib/preferences/storage';
import { connectKnowledgeJobEvents } from '../shared/knowledge-events';
import { upsertRecentJobRecord } from '../shared/knowledge-jobs';
import { useTableSort } from '$lib/components/page/table/use-table-sort.svelte';
import {
  buildIngestMetadata,
  DEFAULT_SCANNED_FILE_SORT,
  optionalInt,
  readPersistedKnowledgeFolder,
  SCANNED_FILE_SORT_COLUMNS,
  sortScannedFiles,
  writePersistedKnowledgeFolder
} from '../shared/knowledge-pure';
import type { KnowledgeOptionsModel } from './knowledge-options.svelte';

/** L3 (Phase 5f) — status of the post-ingest graph-build step. */
export type GraphBuildStatus = 'idle' | 'running' | 'completed' | 'failed';

/** Ingest tab: folder scan, file selection, job tracking. */
export function createKnowledgeIngestModel(deps: {
  options: KnowledgeOptionsModel;
  setError: (message: string | null) => void;
  onJobTerminal: () => void;
}) {
  let folder = $state('');
  let ownerKind = $state<KnowledgeIngestMetadata['owner_kind']>('system');
  let ownerId = $state('0');
  let categoryId = $state('');
  let subcategoryId = $state('');
  let ingestTags = $state<string[]>([]);
  let scanning = $state(false);
  let hasScanned = $state(false);
  let showOnlySupported = $state(true);
  let pickingFolder = $state(false);
  let ingesting = $state(false);
  let files = $state<KnowledgeScannedFile[]>([]);
  let selected = $state<Record<string, boolean>>({});
  let job = $state<KnowledgeJobData | null>(null);
  let recentJobs = $state<KnowledgeJobRecord[]>([]);
  let activeErrorsJobId = $state<string | null>(null);

  // L3 (Phase 5f) — "Also build entity graph (L3)" checkbox state.
  // Persisted to localStorage so the user's default sticks across reloads.
  let buildGraphAfter = $state<boolean>(
    readLocalBoolean(PREF_KEYS.knowledgeIngestBuildGraph, false)
  );
  // When the user ingests with this checked, the controller remembers WHICH
  // paths it sent so the post-ingest auto-graph step can resolve them back to
  // document IDs (via listKnowledgeDocuments + source_uri match).
  let lastOwnedIngestPaths = $state<string[]>([]);
  let graphBuildStatus = $state<GraphBuildStatus>('idle');
  let graphBuildResult = $state<KnowledgeGraphIngestBatchData | null>(null);
  let graphBuildError = $state<string | null>(null);

  const fileSort = useTableSort({
    defaultBy: DEFAULT_SCANNED_FILE_SORT.column,
    defaultDirection: DEFAULT_SCANNED_FILE_SORT.direction,
    allowed: SCANNED_FILE_SORT_COLUMNS
  });

  const selectedPaths = $derived(
    files.filter((file) => file.supported && selected[file.path]).map((file) => file.path)
  );
  const supportedFiles = $derived(files.filter((file) => file.supported));
  const readyFiles = $derived(files.filter((file) => file.supported && !file.already_ingested));
  const visibleFiles = $derived(showOnlySupported ? supportedFiles : files);
  const sortedVisibleFiles = $derived(
    sortScannedFiles(visibleFiles, fileSort.sortBy, fileSort.direction)
  );
  const allSupportedSelected = $derived(
    supportedFiles.length > 0 && supportedFiles.every((file) => selected[file.path])
  );
  const allReadySelected = $derived(
    readyFiles.length > 0 &&
      readyFiles.every((file) => selected[file.path]) &&
      supportedFiles.every((file) => !file.already_ingested || !selected[file.path])
  );
  const someSupportedSelected = $derived(
    supportedFiles.some((file) => selected[file.path]) && !allSupportedSelected
  );
  const subcategories = $derived(
    deps.options.categories.filter((category) => category.parent_id === optionalInt(categoryId))
  );
  const currentJobRecord = $derived(recentJobs.find((item) => item.id === job?.job_id) ?? null);
  const jobTotal = $derived(Math.max(1, job?.totals.requested ?? 1));
  const jobDone = $derived(
    (job?.totals.ingested ?? 0) + (job?.totals.skipped ?? 0) + (job?.totals.failed ?? 0)
  );
  const jobPercent = $derived(Math.min(100, Math.round((jobDone / jobTotal) * 100)));

  function applyJobUpdate(nextJob: KnowledgeJobData) {
    job = nextJob;
    recentJobs = upsertRecentJobRecord(recentJobs, nextJob);
    if (nextJob.status !== 'running') {
      deps.onJobTerminal();
      // L3 (Phase 5f) — when this terminal event belongs to an ingest WE just
      // kicked off (i.e. we have lastOwnedIngestPaths) AND the user opted into
      // post-ingest graph build AND the job actually succeeded → resolve the
      // paths to doc ids and fire off the batch graph ingest. Cleared after
      // trigger so receiving the same terminal event twice doesn't re-fire.
      if (
        nextJob.status === 'completed'
        && buildGraphAfter
        && lastOwnedIngestPaths.length > 0
      ) {
        const paths = lastOwnedIngestPaths;
        lastOwnedIngestPaths = [];
        void autoBuildGraphForPaths(paths);
      } else if (nextJob.status !== 'completed') {
        // Failed ingest → nothing to graph; clear so a later success doesn't
        // accidentally pick up the stale paths.
        lastOwnedIngestPaths = [];
      }
    }
  }

  /** Look up the just-ingested documents (by source_uri = one of ``paths``)
   *  and trigger ``POST /knowledge/graph/ingest_batch``. Runs sync from the
   *  controller's view (the API call awaits the full batch). Failures land
   *  in graphBuildError but don't surface as a page-level error — the user
   *  already sees the (successful) ingest job in the UI; graph-build failure
   *  is its own side-channel. */
  async function autoBuildGraphForPaths(paths: string[]) {
    graphBuildStatus = 'running';
    graphBuildError = null;
    graphBuildResult = null;
    try {
      // Pull recent docs and filter by source_uri match. Limit=500 covers
      // any reasonable batch; if the user uploads thousands at once, the
      // overflow simply doesn't get auto-graphed (they can re-ingest later).
      const pathSet = new Set(paths.map((p) => p.replace(/\\/g, '/')));
      const docs = await listKnowledgeDocuments({ limit: 500 });
      const docIds = docs.data.documents
        .filter((d) => pathSet.has(String(d.source_uri).replace(/\\/g, '/')))
        .map((d) => d.id);
      if (docIds.length === 0) {
        graphBuildStatus = 'completed';
        graphBuildResult = { document_count: 0, documents: [], totals: {} };
        return;
      }
      const result = await runKnowledgeGraphIngestBatch(docIds);
      graphBuildResult = result.data;
      graphBuildStatus = 'completed';
    } catch (err) {
      graphBuildStatus = 'failed';
      graphBuildError = err instanceof Error ? err.message : 'Graph build failed.';
    }
  }

  function setBuildGraphAfter(on: boolean) {
    buildGraphAfter = on;
    writeLocalBoolean(PREF_KEYS.knowledgeIngestBuildGraph, on);
  }

  /** Drop the last graph-build result (the "X" button next to the status line). */
  function clearGraphBuildResult() {
    graphBuildResult = null;
    graphBuildError = null;
    graphBuildStatus = 'idle';
  }

  async function loadJobs() {
    try {
      const payload = await listKnowledgeJobs(10);
      recentJobs = payload.data.jobs;
      const running = payload.data.jobs.find((item) => item.status === 'running');
      if (running && !job) {
        job = {
          job_id: running.id,
          status: running.status,
          totals: running.totals,
          errors: running.errors
        };
      }
    } catch (err) {
      deps.setError(err instanceof Error ? err.message : 'Could not load knowledge jobs.');
    }
  }

  function restoreFolderFromStorage() {
    folder = readPersistedKnowledgeFolder();
  }

  function persistFolder(value = folder) {
    writePersistedKnowledgeFolder(value);
  }

  function connectEvents() {
    return connectKnowledgeJobEvents(applyJobUpdate);
  }

  async function browseFolder() {
    pickingFolder = true;
    deps.setError(null);
    try {
      const payload = await pickKnowledgeFolder(folder.trim() || undefined);
      if (payload.data.folder) {
        folder = payload.data.folder;
        persistFolder(folder);
        await scan();
      }
    } catch (err) {
      deps.setError(err instanceof Error ? err.message : 'Folder picker failed.');
    } finally {
      pickingFolder = false;
    }
  }

  function onFolderChange() {
    hasScanned = false;
    files = [];
    selected = {};
    if (!folder.trim()) {
      persistFolder('');
    }
  }

  function onFolderBlur() {
    persistFolder();
  }

  async function openIngestFolder() {
    const path = folder.trim();
    if (!path) return;
    deps.setError(null);
    try {
      await openWorkspaceFolder(path);
    } catch (err) {
      deps.setError(err instanceof Error ? err.message : 'Open folder failed.');
    }
  }

  async function scan() {
    if (!folder.trim()) return;
    scanning = true;
    deps.setError(null);
    try {
      persistFolder();
      const payload = await scanKnowledgeFolder(folder.trim(), true);
      files = payload.data.files;
      selected = {};
      hasScanned = true;
    } catch (err) {
      deps.setError(err instanceof Error ? err.message : 'Folder scan failed.');
    } finally {
      scanning = false;
    }
  }

  function handleOwnerKindChange() {
    if (ownerKind === 'system') {
      ownerId = '0';
    } else if (ownerKind === 'character') {
      ownerId = String(deps.options.characters[0]?.id ?? '');
    } else {
      ownerId = String(deps.options.users[0]?.id ?? '');
    }
  }

  async function ingestSelected() {
    if (!selectedPaths.length) return;
    ingesting = true;
    deps.setError(null);
    // Capture paths BEFORE the API call so the post-ingest auto-graph hook in
    // applyJobUpdate has them; cleared on failure or after the terminal event
    // fires the graph-build trigger.
    lastOwnedIngestPaths = buildGraphAfter ? [...selectedPaths] : [];
    // Fresh status for this ingest's graph-build outcome (drop any previous run).
    if (buildGraphAfter) {
      graphBuildStatus = 'idle';
      graphBuildResult = null;
      graphBuildError = null;
    }
    try {
      const payload = await ingestKnowledge(
        selectedPaths,
        buildIngestMetadata({ ownerKind, ownerId, categoryId, subcategoryId, tags: ingestTags })
      );
      applyJobUpdate(payload.data);
    } catch (err) {
      deps.setError(err instanceof Error ? err.message : 'Ingest failed.');
      lastOwnedIngestPaths = [];  // ingest failed → don't trigger graph build later
    } finally {
      ingesting = false;
    }
  }

  async function reingestActiveDocument(documentId: string): Promise<KnowledgeJobData | null> {
    ingesting = true;
    deps.setError(null);
    try {
      const payload = await reingestKnowledgeDocument(documentId);
      applyJobUpdate(payload.data);
      return payload.data;
    } catch (err) {
      deps.setError(err instanceof Error ? err.message : 'Re-ingest failed.');
      return null;
    } finally {
      ingesting = false;
    }
  }

  function selectReadyFiles() {
    selected = Object.fromEntries(readyFiles.map((file) => [file.path, true]));
  }

  function selectAllSupported() {
    selected = Object.fromEntries(supportedFiles.map((file) => [file.path, true]));
  }

  function deselectAll() {
    selected = {};
  }

  /** Header checkbox cycles: ready → ready+indexed → none. */
  function cycleSelectAll() {
    if (supportedFiles.length === 0) return;

    const anySelected = supportedFiles.some((file) => selected[file.path]);
    const indexedAnySelected = supportedFiles.some((file) => file.already_ingested && selected[file.path]);

    if (allSupportedSelected) {
      deselectAll();
      return;
    }
    if (allReadySelected) {
      selectAllSupported();
      return;
    }
    if (!anySelected && readyFiles.length === 0) {
      selectAllSupported();
      return;
    }
    selectReadyFiles();
  }

  function toggleFileSelection(path: string, checked: boolean) {
    selected = { ...selected, [path]: checked };
  }

  async function retryJob(item: KnowledgeJobRecord) {
    const params = item.params as {
      paths?: string[];
      owner_kind?: KnowledgeIngestMetadata['owner_kind'];
      owner_id?: string;
      category_id?: number | null;
      subcategory_id?: number | null;
      tags?: string[];
    };
    const paths = Array.isArray(params.paths) ? params.paths : [];
    if (!paths.length) return;
    ingesting = true;
    deps.setError(null);
    try {
      const payload = await ingestKnowledge(paths, {
        owner_kind: params.owner_kind ?? 'system',
        owner_id: params.owner_id ?? '0',
        category_id: params.category_id ?? null,
        subcategory_id: params.subcategory_id ?? null,
        tags: Array.isArray(params.tags) ? params.tags : []
      });
      applyJobUpdate(payload.data);
    } catch (err) {
      deps.setError(err instanceof Error ? err.message : 'Retry failed.');
    } finally {
      ingesting = false;
    }
  }

  function toggleActiveErrorsJobId(jobId: string) {
    activeErrorsJobId = activeErrorsJobId === jobId ? null : jobId;
  }

  return {
    get folder() {
      return folder;
    },
    set folder(v: string) {
      folder = v;
    },
    get ownerKind() {
      return ownerKind;
    },
    set ownerKind(v: KnowledgeIngestMetadata['owner_kind']) {
      ownerKind = v;
    },
    get ownerId() {
      return ownerId;
    },
    set ownerId(v: string) {
      ownerId = v;
    },
    get categoryId() {
      return categoryId;
    },
    set categoryId(v: string) {
      categoryId = v;
    },
    get subcategoryId() {
      return subcategoryId;
    },
    set subcategoryId(v: string) {
      subcategoryId = v;
    },
    get ingestTags() {
      return ingestTags;
    },
    set ingestTags(v: string[]) {
      ingestTags = v;
    },
    get scanning() {
      return scanning;
    },
    get hasScanned() {
      return hasScanned;
    },
    get showOnlySupported() {
      return showOnlySupported;
    },
    set showOnlySupported(v: boolean) {
      showOnlySupported = v;
    },
    get pickingFolder() {
      return pickingFolder;
    },
    get ingesting() {
      return ingesting;
    },
    get files() {
      return files;
    },
    get selected() {
      return selected;
    },
    get job() {
      return job;
    },
    get recentJobs() {
      return recentJobs;
    },
    get activeErrorsJobId() {
      return activeErrorsJobId;
    },
    set activeErrorsJobId(v: string | null) {
      activeErrorsJobId = v;
    },
    get selectedPaths() {
      return selectedPaths;
    },
    get supportedFiles() {
      return supportedFiles;
    },
    get visibleFiles() {
      return visibleFiles;
    },
    get sortedVisibleFiles() {
      return sortedVisibleFiles;
    },
    get fileSort() {
      return fileSort;
    },
    get allSupportedSelected() {
      return allSupportedSelected;
    },
    get allReadySelected() {
      return allReadySelected;
    },
    get someSupportedSelected() {
      return someSupportedSelected;
    },
    get subcategories() {
      return subcategories;
    },
    get currentJobRecord() {
      return currentJobRecord;
    },
    get jobTotal() {
      return jobTotal;
    },
    get jobDone() {
      return jobDone;
    },
    get jobPercent() {
      return jobPercent;
    },
    // L3 (Phase 5f) — "Also build entity graph" post-ingest toggle + status.
    get buildGraphAfter() {
      return buildGraphAfter;
    },
    setBuildGraphAfter,
    get graphBuildStatus() {
      return graphBuildStatus;
    },
    get graphBuildResult() {
      return graphBuildResult;
    },
    get graphBuildError() {
      return graphBuildError;
    },
    clearGraphBuildResult,
    restoreFolderFromStorage,
    connectEvents,
    loadJobs,
    browseFolder,
    onFolderChange,
    onFolderBlur,
    openIngestFolder,
    scan,
    handleOwnerKindChange,
    ingestSelected,
    reingestActiveDocument,
    cycleSelectAll,
    toggleFileSelection,
    retryJob,
    toggleActiveErrorsJobId
  };
}

export type KnowledgeIngestModel = ReturnType<typeof createKnowledgeIngestModel>;
