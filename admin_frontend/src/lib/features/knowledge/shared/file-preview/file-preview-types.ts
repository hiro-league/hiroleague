/** File preview formats returned by `/knowledge/preview-file`. Add new formats here and a matching renderer. */
export type FilePreviewFormat = 'markdown' | 'plain-text' | 'unsupported';

export type KnowledgeFilePreviewData = {
  path: string;
  relative_path: string;
  ext: string;
  mime: string | null;
  format: FilePreviewFormat;
  supported: boolean;
  content: string | null;
  disabled_reason: string | null;
  truncated: boolean;
  line_count: number;
  character_count: number;
  estimated_tokens: number;
};

export type FilePreviewMetrics = Pick<
  KnowledgeFilePreviewData,
  'line_count' | 'character_count' | 'estimated_tokens'
>;
