import { apiRequest, type ApiResponse } from './client';

export type KnowledgeScannedFile = {
  path: string;
  relative_path: string;
  ext: string;
  size_bytes: number;
  supported: boolean;
  already_ingested: boolean;
  disabled_reason: string | null;
};

export type KnowledgeCategory = {
  id: number;
  name: string;
  parent_id: number | null;
};

export type KnowledgeTag = {
  id: number;
  name: string;
};

export type KnowledgeOwnerOption = {
  id: string | number;
  name: string;
};

export type KnowledgeOptionsData = {
  categories: KnowledgeCategory[];
  tags: KnowledgeTag[];
  characters: KnowledgeOwnerOption[];
  users: KnowledgeOwnerOption[];
};

export type KnowledgeScanData = {
  root: string;
  files: KnowledgeScannedFile[];
};

export type KnowledgeJobData = {
  job_id: string;
  status: string;
  totals: Record<string, number>;
  errors: Record<string, string>;
  in_flight?: string[];
};

export type KnowledgeJobRecord = {
  id: string;
  created_at: string;
  finished_at: string | null;
  status: string;
  totals: Record<string, number>;
  errors: Record<string, string>;
  params: Record<string, unknown>;
};

export type KnowledgeListJobsData = {
  jobs: KnowledgeJobRecord[];
};

export type KnowledgeDocument = {
  id: string;
  source_uri: string;
  source_type: string;
  mime: string;
  ext: string;
  owner_kind: string;
  owner_id: string;
  category_id: number | null;
  subcategory_id: number | null;
  title: string;
  content_hash: string | null;
  size_bytes: number;
  chunk_count: number | null;
  status: string;
  error: string | null;
  ingested_at: string | null;
  updated_at: string;
  tags: string[];
};

export type KnowledgeListDocumentsData = {
  documents: KnowledgeDocument[];
  total: number;
};

export type KnowledgeChunk = {
  point_id: string;
  document_id: string;
  ord: number;
  text: string;
  heading_path: string | null;
  title: string;
  source_uri: string;
  score?: number;
  [key: string]: unknown;
};

export type KnowledgeDocumentDetailData = {
  document: KnowledgeDocument | null;
  chunks: KnowledgeChunk[];
  chunk_next_offset?: string | null;
};

export type KnowledgeSearchHit = {
  document_id: string;
  point_id: string;
  score: number;
  ord: number;
  text: string;
  heading_path: string | null;
  title: string;
  source_uri: string;
  owner_kind: string;
  owner_id: string;
  category_id: number | null;
  subcategory_id: number | null;
  tags: string[];
};

export type KnowledgeSearchData = {
  query: string;
  hits: KnowledgeSearchHit[];
};

export type KnowledgeSource = {
  ref: number;
  document_id: string;
  point_id: string;
  title: string;
  heading_path: string | null;
  source_uri: string;
  score: number;
  text: string;
  owner_kind: string;
  owner_id: string;
  category_id: number | null;
  subcategory_id: number | null;
  tags: string[];
};

export type KnowledgeAnswerData = {
  query: string;
  answer: string;
  sources: KnowledgeSource[];
  elapsed_ms: number;
  model_id: string | null;
  usage: Record<string, number | string | boolean | null>;
  no_results: boolean;
};

export type KnowledgeFilters = {
  owner_kind?: string | null;
  owner_id?: string | null;
  category_id?: number | null;
  subcategory_id?: number | null;
  document_id?: string | null;
  tags?: string[];
};

export type KnowledgeFilePreviewData = {
  path: string;
  relative_path: string;
  ext: string;
  mime: string | null;
  format: 'markdown' | 'plain-text' | 'unsupported';
  supported: boolean;
  content: string | null;
  disabled_reason: string | null;
  truncated: boolean;
  line_count: number;
  character_count: number;
  estimated_tokens: number;
};

export function scanKnowledgeFolder(folder: string, recursive = true): Promise<ApiResponse<KnowledgeScanData>> {
  return apiRequest<KnowledgeScanData>('/knowledge/scan-folder', {
    method: 'POST',
    body: { folder, recursive },
    timeoutMs: 60000
  });
}

export function pickKnowledgeFolder(initialFolder?: string): Promise<ApiResponse<{ folder: string | null }>> {
  return apiRequest<{ folder: string | null }>('/knowledge/pick-folder', {
    method: 'POST',
    body: { initial_folder: initialFolder ?? null },
    timeoutMs: 300000
  });
}

export function previewKnowledgeFile(path: string): Promise<ApiResponse<KnowledgeFilePreviewData>> {
  return apiRequest<KnowledgeFilePreviewData>('/knowledge/preview-file', {
    method: 'POST',
    body: { path },
    timeoutMs: 60000
  });
}

export function getKnowledgeOptions(): Promise<ApiResponse<KnowledgeOptionsData>> {
  return apiRequest<KnowledgeOptionsData>('/knowledge/options', {
    timeoutMs: 60000
  });
}

export function createKnowledgeCategory(
  name: string,
  parentId: number | null = null
): Promise<ApiResponse<KnowledgeCategory>> {
  return apiRequest<KnowledgeCategory>('/knowledge/categories', {
    method: 'POST',
    body: { name, parent_id: parentId },
    timeoutMs: 60000
  });
}

export function createKnowledgeTag(name: string): Promise<ApiResponse<KnowledgeTag>> {
  return apiRequest<KnowledgeTag>('/knowledge/tags', {
    method: 'POST',
    body: { name },
    timeoutMs: 60000
  });
}

export type KnowledgeIngestMetadata = {
  owner_kind: 'system' | 'character' | 'user';
  owner_id: string;
  category_id: number | null;
  subcategory_id: number | null;
  tags: string[];
};

export function ingestKnowledge(
  paths: string[],
  metadata: KnowledgeIngestMetadata
): Promise<ApiResponse<KnowledgeJobData>> {
  return apiRequest<KnowledgeJobData>('/knowledge/ingest', {
    method: 'POST',
    body: { paths, ...metadata, wait: false },
    timeoutMs: 60000
  });
}

export function getKnowledgeJob(jobId: string): Promise<ApiResponse<KnowledgeJobData>> {
  return apiRequest<KnowledgeJobData>(`/knowledge/jobs/${encodeURIComponent(jobId)}`, {
    timeoutMs: 60000
  });
}

export function listKnowledgeJobs(limit = 20): Promise<ApiResponse<KnowledgeListJobsData>> {
  return apiRequest<KnowledgeListJobsData>(`/knowledge/jobs?limit=${encodeURIComponent(String(limit))}`);
}

export function searchKnowledge(
  query: string,
  topK = 10,
  minScore = 0,
  filters: KnowledgeFilters = {}
): Promise<ApiResponse<KnowledgeSearchData>> {
  return apiRequest<KnowledgeSearchData>('/knowledge/search', {
    method: 'POST',
    body: { query, top_k: topK, min_score: minScore, filters },
    timeoutMs: 120000
  });
}

export function answerKnowledge(
  query: string,
  topK = 20,
  minScore = 0,
  filters: KnowledgeFilters = {}
): Promise<ApiResponse<KnowledgeAnswerData>> {
  return apiRequest<KnowledgeAnswerData>('/knowledge/answer', {
    method: 'POST',
    body: { query, top_k: topK, min_score: minScore, filters },
    timeoutMs: 180000
  });
}

export function listKnowledgeDocuments(filters: {
  status?: string;
  owner_kind?: string;
  owner_id?: string;
  category_id?: number | null;
  subcategory_id?: number | null;
  tag?: string;
  source_type?: string;
  title?: string;
  limit?: number;
  offset?: number;
} = {}): Promise<ApiResponse<KnowledgeListDocumentsData>> {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== null && String(value).trim() !== '') {
      params.set(key, String(value));
    }
  }
  const suffix = params.toString() ? `?${params.toString()}` : '';
  return apiRequest<KnowledgeListDocumentsData>(`/knowledge/documents${suffix}`);
}

export function getKnowledgeDocument(
  documentId: string,
  options?: { chunkLimit?: number; chunkOffset?: string | null }
): Promise<ApiResponse<KnowledgeDocumentDetailData>> {
  const params = new URLSearchParams();
  if (options?.chunkLimit != null) params.set('chunk_limit', String(options.chunkLimit));
  if (options?.chunkOffset) params.set('chunk_offset', options.chunkOffset);
  const suffix = params.toString() ? `?${params.toString()}` : '';
  return apiRequest<KnowledgeDocumentDetailData>(
    `/knowledge/documents/${encodeURIComponent(documentId)}${suffix}`
  );
}

export function deleteKnowledgeDocument(documentId: string): Promise<ApiResponse<{ document_id: string; deleted: boolean }>> {
  return apiRequest<{ document_id: string; deleted: boolean }>(`/knowledge/documents/${encodeURIComponent(documentId)}`, {
    method: 'DELETE',
    timeoutMs: 60000
  });
}

export function reingestKnowledgeDocument(documentId: string): Promise<ApiResponse<KnowledgeJobData>> {
  return apiRequest<KnowledgeJobData>(`/knowledge/documents/${encodeURIComponent(documentId)}/reingest`, {
    method: 'POST'
  });
}

export function updateKnowledgeDocumentMetadata(
  documentId: string,
  metadata: KnowledgeIngestMetadata
): Promise<ApiResponse<KnowledgeDocument>> {
  return apiRequest<KnowledgeDocument>(`/knowledge/documents/${encodeURIComponent(documentId)}/metadata`, {
    method: 'PATCH',
    body: metadata,
    timeoutMs: 60000
  });
}
