/**
 * Side-effect-free helpers for Knowledge admin UI (ingest, ask, browse).
 * Kept separate from KnowledgePage.svelte so formatting and parsing stay unit-testable.
 */
import { preferenceTabHref } from '$lib/features/preferences/shared/preferences-tabs';
import { PREF_KEYS } from '$lib/preferences/keys';
import {
  readLocalBoolean,
  readLocalString,
  readSessionString,
  removeLocalString,
  removeSessionString,
  writeLocalBoolean,
  writeLocalString,
  writeSessionString
} from '$lib/preferences/storage';
import type {
  KnowledgeAnswerCompareData,
  KnowledgeAnswerData,
  KnowledgeDocument,
  KnowledgeFilters,
  KnowledgeGraphMode,
  KnowledgeIngestMetadata,
  KnowledgeScannedFile
} from '$lib/api/knowledge';

export type KnowledgeTabId = 'ingest' | 'ask' | 'browse' | 'eval';

export function normalizeKnowledgeTab(value: string | null | undefined): KnowledgeTabId | null {
  if (value === 'ingest' || value === 'browse' || value === 'ask' || value === 'eval') return value;
  return null;
}

export const KNOWLEDGE_TABS: { id: KnowledgeTabId; label: string }[] = [
  { id: 'browse', label: 'Browse' },
  { id: 'ingest', label: 'Add' },
  { id: 'ask', label: 'Ask' },
  { id: 'eval', label: 'Eval' }
];

/** Deep link to workspace Knowledge preferences (embedding, retrieval, chunking, answering). */
export const KNOWLEDGE_PREFERENCES_SECTION_HREF = preferenceTabHref('knowledge');

/** Deep link to Knowledge admin Browse tab (`/knowledge/` — default tab omits `?tab=`). */
export function knowledgeTabHref(tab: KnowledgeTabId, basePath = ''): string {
  if (tab === 'browse') {
    return `${basePath}/knowledge/`;
  }
  return `${basePath}/knowledge/?tab=${tab}`;
}

export const KNOWLEDGE_BROWSE_HREF = knowledgeTabHref('browse');

/** Browse chunk list page size; fetch one extra to detect a further page. */
export const KNOWLEDGE_CHUNK_PAGE_SIZE = 100;
export const KNOWLEDGE_CHUNK_FETCH_SIZE = KNOWLEDGE_CHUNK_PAGE_SIZE + 1;

export function selectedWorkspaceId(): string {
  return typeof localStorage === 'undefined'
    ? 'default'
    : (localStorage.getItem(PREF_KEYS.selectedWorkspace) ?? 'default');
}

export function folderStorageKey(): string {
  return `${PREF_KEYS.knowledgeLastFolderPrefix}.${selectedWorkspaceId()}`;
}

/** Last folder path for the Add tab (per workspace); empty string when unset. */
export function readPersistedKnowledgeFolder(): string {
  return readLocalString(folderStorageKey()) ?? '';
}

export function writePersistedKnowledgeFolder(folder: string) {
  const trimmed = folder.trim();
  const key = folderStorageKey();
  if (!trimmed) {
    removeLocalString(key);
    return;
  }
  writeLocalString(key, trimmed);
}

/** Browse chunk list: formatted markdown vs raw source text (default formatted). */
export function readKnowledgeChunkMarkdownFormat(): boolean {
  return readLocalBoolean(PREF_KEYS.knowledgeChunkMarkdownFormat, true);
}

export function writeKnowledgeChunkMarkdownFormat(enabled: boolean) {
  writeLocalBoolean(PREF_KEYS.knowledgeChunkMarkdownFormat, enabled);
}

/**
 * Ask tab last-answer persistence. Asking costs an LLM call, so the answer + chunk results are
 * cached in sessionStorage and survive navigating away to other admin pages and back, until the
 * user asks a new question, clears the result, or closes the browser tab.
 */
export function readPersistedKnowledgeAskResult(): KnowledgeAnswerData | null {
  const raw = readSessionString(PREF_KEYS.knowledgeAskResult);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as KnowledgeAnswerData;
  } catch {
    // Corrupt/stale payload — drop it rather than crashing the Ask tab on mount.
    removeSessionString(PREF_KEYS.knowledgeAskResult);
    return null;
  }
}

export function writePersistedKnowledgeAskResult(result: KnowledgeAnswerData) {
  writeSessionString(PREF_KEYS.knowledgeAskResult, JSON.stringify(result));
}

export function clearPersistedKnowledgeAskResult() {
  removeSessionString(PREF_KEYS.knowledgeAskResult);
}

/** L3 — compare-mode last-result persistence (parallel to askResult above). */
export function readPersistedKnowledgeAskCompareResult(): KnowledgeAnswerCompareData | null {
  const raw = readSessionString(PREF_KEYS.knowledgeAskCompareResult);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as KnowledgeAnswerCompareData;
  } catch {
    removeSessionString(PREF_KEYS.knowledgeAskCompareResult);
    return null;
  }
}

export function writePersistedKnowledgeAskCompareResult(result: KnowledgeAnswerCompareData) {
  writeSessionString(PREF_KEYS.knowledgeAskCompareResult, JSON.stringify(result));
}

export function clearPersistedKnowledgeAskCompareResult() {
  removeSessionString(PREF_KEYS.knowledgeAskCompareResult);
}

/** L3 — graph mode preference (localStorage so it persists across browser sessions). */
const VALID_GRAPH_MODES: KnowledgeGraphMode[] = ['off', 'on', 'compare'];

export function readPersistedKnowledgeGraphMode(): KnowledgeGraphMode {
  const raw = readLocalString(PREF_KEYS.knowledgeAskGraphMode) ?? 'off';
  return VALID_GRAPH_MODES.includes(raw as KnowledgeGraphMode)
    ? (raw as KnowledgeGraphMode)
    : 'off';
}

export function writePersistedKnowledgeGraphMode(mode: KnowledgeGraphMode) {
  writeLocalString(PREF_KEYS.knowledgeAskGraphMode, mode);
}

export function fileName(relativePath: string): string {
  return relativePath.split(/[\\/]/).pop() || relativePath;
}

/** Map an indexed document to the file-preview dialog target (reuses Add-tab preview API). */
export function documentToPreviewFile(doc: KnowledgeDocument): KnowledgeScannedFile {
  return {
    path: doc.source_uri,
    relative_path: doc.source_uri,
    ext: doc.ext,
    size_bytes: doc.size_bytes,
    supported: true,
    already_ingested: true,
    disabled_reason: null
  };
}

/** Directory portion of a scanned relative path (empty when the file is at the scan root). */
export function relativeFolderPath(relativePath: string): string {
  const parts = relativePath.split(/[\\/]/);
  if (parts.length <= 1) return '';
  parts.pop();
  return parts.join('/');
}

export function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

/** UTF-8 byte length of chunk text (derived; not stored in the vector payload). */
export function chunkTextByteSize(text: string): number {
  return new TextEncoder().encode(text).length;
}

export function documentFileTypeLabel(doc: KnowledgeDocument): string {
  return doc.ext || 'none';
}

/** MIME for display (e.g. ``text/markdown``); falls back to extension when mime is unset. */
export function documentMimeLabel(doc: KnowledgeDocument): string {
  const mime = doc.mime?.trim();
  if (mime) return mime;
  if (doc.ext?.trim()) return doc.ext.trim();
  return 'unknown';
}

export function documentFileTypeTooltip(doc: KnowledgeDocument): string | undefined {
  if (!doc.mime?.trim()) return undefined;
  return doc.mime.trim();
}

/** Error text for Status hover; ingested/type/path are shown in their own columns. */
export function documentStatusErrorTooltip(doc: KnowledgeDocument): string | undefined {
  const error = doc.error?.trim();
  return error || undefined;
}

export function tagsFromText(value: string): string[] {
  return value
    .split(',')
    .map((tag) => tag.trim())
    .filter(Boolean);
}

export function optionalInt(value: string): number | null {
  const trimmed = value.trim();
  return trimmed ? Number.parseInt(trimmed, 10) : null;
}

export function buildIngestMetadata(input: {
  ownerKind: KnowledgeIngestMetadata['owner_kind'];
  ownerId: string;
  categoryId: string;
  subcategoryId: string;
  tags: string[];
}): KnowledgeIngestMetadata {
  return {
    owner_kind: input.ownerKind,
    owner_id: input.ownerId.trim() || (input.ownerKind === 'system' ? '0' : ''),
    category_id: optionalInt(input.categoryId),
    subcategory_id: optionalInt(input.subcategoryId),
    tags: input.tags
  };
}

export function buildAskFilters(input: {
  askOwnerKind: string;
  askOwnerId: string;
  askCategoryId: string;
  askSubcategoryId: string;
  askTags: string[];
  askDocumentId: string | null;
}): KnowledgeFilters {
  return {
    owner_kind: input.askOwnerKind || null,
    owner_id: input.askOwnerId || null,
    category_id: optionalInt(input.askCategoryId),
    subcategory_id: optionalInt(input.askSubcategoryId),
    tags: input.askTags,
    document_id: input.askDocumentId
  };
}

export function jobElapsed(createdAt: string): string {
  const started = new Date(createdAt).getTime();
  if (!Number.isFinite(started)) return '';
  const seconds = Math.max(0, Math.round((Date.now() - started) / 1000));
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

export type JobTotalsLike = Record<string, number>;

export function formatJobTotalsSummary(totals: JobTotalsLike): string {
  return `${totals.ingested ?? 0} ingested, ${totals.skipped ?? 0} skipped, ${totals.failed ?? 0} failed, ${totals.chunks ?? 0} chunks`;
}

export function sumJobTotals(jobs: ReadonlyArray<{ totals: JobTotalsLike }>): JobTotalsLike {
  const sum: JobTotalsLike = { ingested: 0, skipped: 0, failed: 0, chunks: 0 };
  for (const job of jobs) {
    sum.ingested = (sum.ingested ?? 0) + (job.totals.ingested ?? 0);
    sum.skipped = (sum.skipped ?? 0) + (job.totals.skipped ?? 0);
    sum.failed = (sum.failed ?? 0) + (job.totals.failed ?? 0);
    sum.chunks = (sum.chunks ?? 0) + (job.totals.chunks ?? 0);
  }
  return sum;
}

export function formatRecentJobsHeaderSummary(
  jobs: ReadonlyArray<{ totals: JobTotalsLike }>
): string {
  const jobCount = jobs.length;
  const jobLabel = jobCount === 1 ? '1 job' : `${jobCount} jobs`;
  return `${jobLabel} · ${formatJobTotalsSummary(sumJobTotals(jobs))}`;
}

export function formatIngestHeaderSummary(selectedCount: number, jobStatus?: string | null): string {
  const parts: string[] = [];
  if (selectedCount > 0) {
    parts.push(selectedCount === 1 ? '1 file selected' : `${selectedCount} files selected`);
  }
  if (jobStatus) {
    parts.push(jobStatus);
  }
  return parts.join(' · ');
}

export type ScannedFileSortColumn = 'filename' | 'relative_path' | 'size' | 'ext' | 'state';
export type ScannedFileSortDirection = 'asc' | 'desc';

export const DEFAULT_SCANNED_FILE_SORT: {
  column: ScannedFileSortColumn;
  direction: ScannedFileSortDirection;
} = {
  column: 'relative_path',
  direction: 'asc'
};

export const SCANNED_FILE_SORT_COLUMNS = [
  'filename',
  'relative_path',
  'size',
  'ext',
  'state'
] as const satisfies readonly ScannedFileSortColumn[];

const LOCALE_OPTS: Intl.CollatorOptions = { sensitivity: 'base', numeric: true };

function compareText(a: string, b: string): number {
  return a.localeCompare(b, undefined, LOCALE_OPTS);
}

export function scannedFileStateLabel(file: KnowledgeScannedFile): string {
  if (file.already_ingested) return 'indexed';
  if (file.supported) return 'ready';
  return 'blocked';
}

export function compareScannedFiles(
  a: KnowledgeScannedFile,
  b: KnowledgeScannedFile,
  column: ScannedFileSortColumn,
  direction: ScannedFileSortDirection
): number {
  let cmp = 0;
  switch (column) {
    case 'filename':
      cmp = compareText(fileName(a.relative_path), fileName(b.relative_path));
      if (cmp === 0) cmp = compareText(relativeFolderPath(a.relative_path), relativeFolderPath(b.relative_path));
      break;
    case 'relative_path':
      cmp = compareText(relativeFolderPath(a.relative_path), relativeFolderPath(b.relative_path));
      if (cmp === 0) cmp = compareText(fileName(a.relative_path), fileName(b.relative_path));
      break;
    case 'size':
      cmp = a.size_bytes - b.size_bytes;
      break;
    case 'ext':
      cmp = compareText(a.ext || '', b.ext || '');
      break;
    case 'state':
      cmp = compareText(scannedFileStateLabel(a), scannedFileStateLabel(b));
      break;
  }
  if (cmp === 0) cmp = compareText(a.relative_path, b.relative_path);
  return direction === 'asc' ? cmp : -cmp;
}

export function sortScannedFiles(
  files: KnowledgeScannedFile[],
  column: ScannedFileSortColumn,
  direction: ScannedFileSortDirection
): KnowledgeScannedFile[] {
  return [...files].sort((a, b) => compareScannedFiles(a, b, column, direction));
}

export type DocumentSortColumn =
  | 'title'
  | 'owner'
  | 'category'
  | 'tags'
  | 'chunks'
  | 'ingested_at'
  | 'type'
  | 'size'
  | 'path'
  | 'status';

export type DocumentSortDirection = 'asc' | 'desc';

export const DEFAULT_DOCUMENT_SORT: {
  column: DocumentSortColumn;
  direction: DocumentSortDirection;
} = {
  column: 'ingested_at',
  direction: 'desc'
};

export const DOCUMENT_SORT_COLUMNS = [
  'title',
  'owner',
  'category',
  'tags',
  'chunks',
  'ingested_at',
  'type',
  'size',
  'path',
  'status'
] as const satisfies readonly DocumentSortColumn[];

function parseIsoMs(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const ms = Date.parse(iso);
  return Number.isNaN(ms) ? null : ms;
}

function compareNullableNumber(a: number | null, b: number | null): number {
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  return a - b;
}

function documentOwnerKey(doc: KnowledgeDocument): string {
  return `${doc.owner_kind}/${doc.owner_id}`;
}

function documentCategoryKey(doc: KnowledgeDocument, categoryLabel: (id: number | null) => string): string {
  const category = categoryLabel(doc.category_id);
  const subcategory = doc.subcategory_id ? categoryLabel(doc.subcategory_id) : '';
  return subcategory ? `${category} > ${subcategory}` : category;
}

/** Owner, category, and tags line for browse chunk header tooltips. */
export function documentMetadataTitleAttr(
  doc: KnowledgeDocument,
  tags: string[],
  categoryLabel: (id: number | null) => string
): string {
  return `Owner: ${documentOwnerKey(doc)} Category: ${documentCategoryDisplay(doc, categoryLabel)} Tags: ${
    tags.length > 0 ? tags.join(', ') : '—'
  }`;
}

export function documentCategoryDisplay(
  doc: KnowledgeDocument,
  categoryLabel: (id: number | null) => string
): string {
  const category = categoryLabel(doc.category_id);
  if (!category) return '—';
  if (doc.subcategory_id) {
    const subcategory = categoryLabel(doc.subcategory_id);
    return subcategory ? `${category} > ${subcategory}` : category;
  }
  return category;
}

export function compareDocuments(
  a: KnowledgeDocument,
  b: KnowledgeDocument,
  column: DocumentSortColumn,
  direction: DocumentSortDirection,
  categoryLabel: (id: number | null) => string
): number {
  let cmp = 0;
  switch (column) {
    case 'title':
      cmp = compareText(a.title, b.title);
      break;
    case 'owner':
      cmp = compareText(documentOwnerKey(a), documentOwnerKey(b));
      break;
    case 'category':
      cmp = compareText(documentCategoryKey(a, categoryLabel), documentCategoryKey(b, categoryLabel));
      break;
    case 'tags':
      cmp = compareText((a.tags ?? []).join(', '), (b.tags ?? []).join(', '));
      break;
    case 'chunks':
      cmp = compareNullableNumber(a.chunk_count, b.chunk_count);
      break;
    case 'ingested_at':
      cmp = compareNullableNumber(parseIsoMs(a.ingested_at), parseIsoMs(b.ingested_at));
      break;
    case 'type':
      cmp = compareText(documentFileTypeLabel(a), documentFileTypeLabel(b));
      break;
    case 'size':
      cmp = a.size_bytes - b.size_bytes;
      break;
    case 'path':
      cmp = compareText(a.source_uri, b.source_uri);
      break;
    case 'status':
      cmp = compareText(a.status, b.status);
      break;
  }
  if (cmp === 0) cmp = compareText(a.title, b.title);
  if (cmp === 0) cmp = compareText(a.id, b.id);
  return direction === 'asc' ? cmp : -cmp;
}

export function sortDocuments(
  documents: KnowledgeDocument[],
  column: DocumentSortColumn,
  direction: DocumentSortDirection,
  categoryLabel: (id: number | null) => string
): KnowledgeDocument[] {
  return [...documents].sort((a, b) => compareDocuments(a, b, column, direction, categoryLabel));
}
