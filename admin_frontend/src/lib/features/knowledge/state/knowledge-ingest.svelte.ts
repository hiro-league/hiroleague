import {
  ingestKnowledge,
  listKnowledgeJobs,
  pickKnowledgeFolder,
  reingestKnowledgeDocument,
  scanKnowledgeFolder,
  type KnowledgeIngestMetadata,
  type KnowledgeJobData,
  type KnowledgeJobRecord,
  type KnowledgeScannedFile
} from '$lib/api/knowledge';
import { openWorkspaceFolder } from '$lib/api/server';
import { connectKnowledgeJobEvents } from '../shared/knowledge-events';
import { upsertRecentJobRecord } from '../shared/knowledge-jobs';
import {
  buildIngestMetadata,
  DEFAULT_SCANNED_FILE_SORT,
  optionalInt,
  readPersistedKnowledgeFolder,
  sortScannedFiles,
  writePersistedKnowledgeFolder,
  type ScannedFileSortColumn,
  type ScannedFileSortDirection
} from '../shared/knowledge-pure';
import type { KnowledgeOptionsModel } from './knowledge-options.svelte';

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
  let fileSortColumn = $state<ScannedFileSortColumn>(DEFAULT_SCANNED_FILE_SORT.column);
  let fileSortDirection = $state<ScannedFileSortDirection>(DEFAULT_SCANNED_FILE_SORT.direction);

  const selectedPaths = $derived(
    files.filter((file) => file.supported && selected[file.path]).map((file) => file.path)
  );
  const supportedFiles = $derived(files.filter((file) => file.supported));
  const visibleFiles = $derived(showOnlySupported ? supportedFiles : files);
  const sortedVisibleFiles = $derived(
    sortScannedFiles(visibleFiles, fileSortColumn, fileSortDirection)
  );
  const allSupportedSelected = $derived(
    supportedFiles.length > 0 && supportedFiles.every((file) => selected[file.path])
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
    }
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
      selected = Object.fromEntries(
        payload.data.files.filter((file) => file.supported && !file.already_ingested).map((file) => [file.path, true])
      );
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
    try {
      const payload = await ingestKnowledge(
        selectedPaths,
        buildIngestMetadata({ ownerKind, ownerId, categoryId, subcategoryId, tags: ingestTags })
      );
      applyJobUpdate(payload.data);
    } catch (err) {
      deps.setError(err instanceof Error ? err.message : 'Ingest failed.');
    } finally {
      ingesting = false;
    }
  }

  async function reingestActiveDocument(documentId: string) {
    ingesting = true;
    deps.setError(null);
    try {
      const payload = await reingestKnowledgeDocument(documentId);
      applyJobUpdate(payload.data);
    } catch (err) {
      deps.setError(err instanceof Error ? err.message : 'Re-ingest failed.');
    } finally {
      ingesting = false;
    }
  }

  function selectAllSupported() {
    selected = Object.fromEntries(files.filter((file) => file.supported).map((file) => [file.path, true]));
  }

  function deselectAll() {
    selected = {};
  }

  function toggleSelectAllSupported(event: Event) {
    const checked = (event.currentTarget as HTMLInputElement).checked;
    if (checked) selectAllSupported();
    else deselectAll();
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

  function toggleFileSort(column: ScannedFileSortColumn) {
    if (fileSortColumn === column) {
      fileSortDirection = fileSortDirection === 'asc' ? 'desc' : 'asc';
      return;
    }
    fileSortColumn = column;
    fileSortDirection = 'asc';
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
    get fileSortColumn() {
      return fileSortColumn;
    },
    get fileSortDirection() {
      return fileSortDirection;
    },
    get allSupportedSelected() {
      return allSupportedSelected;
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
    toggleSelectAllSupported,
    toggleFileSelection,
    toggleFileSort,
    retryJob,
    toggleActiveErrorsJobId
  };
}

export type KnowledgeIngestModel = ReturnType<typeof createKnowledgeIngestModel>;
