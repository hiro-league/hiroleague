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

export type KnowledgeScanData = {
  root: string;
  files: KnowledgeScannedFile[];
};

export type KnowledgeJobData = {
  job_id: string;
  status: string;
  totals: Record<string, number>;
  errors: Record<string, string>;
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
  content_hash: string;
  size_bytes: number;
  chunk_count: number;
  status: string;
  error: string | null;
  ingested_at: string | null;
  updated_at: string;
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
  tags: string[];
};

export type KnowledgeSearchData = {
  query: string;
  hits: KnowledgeSearchHit[];
};

export function scanKnowledgeFolder(folder: string, recursive = true): Promise<ApiResponse<KnowledgeScanData>> {
  return apiRequest<KnowledgeScanData>('/knowledge/scan-folder', {
    method: 'POST',
    body: { folder, recursive },
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

export function searchKnowledge(query: string, topK = 10): Promise<ApiResponse<KnowledgeSearchData>> {
  return apiRequest<KnowledgeSearchData>('/knowledge/search', {
    method: 'POST',
    body: { query, top_k: topK, min_score: 0, filters: {} },
    timeoutMs: 120000
  });
}

export function listKnowledgeDocuments(): Promise<ApiResponse<KnowledgeListDocumentsData>> {
  return apiRequest<KnowledgeListDocumentsData>('/knowledge/documents');
}

export function getKnowledgeDocument(documentId: string): Promise<ApiResponse<KnowledgeDocumentDetailData>> {
  return apiRequest<KnowledgeDocumentDetailData>(`/knowledge/documents/${encodeURIComponent(documentId)}`);
}
