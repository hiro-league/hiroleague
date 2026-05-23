import type { FilePreviewFormat } from './file-preview-types';

/** Extension → preview format (mirrors server `preview_formats.py`; used for UI hints before fetch). */
const PREVIEW_FORMAT_BY_EXTENSION: Record<string, FilePreviewFormat> = {
  '.md': 'markdown'
};

export function resolvePreviewFormat(ext: string, supported: boolean): FilePreviewFormat {
  if (!supported) return 'unsupported';
  return PREVIEW_FORMAT_BY_EXTENSION[ext.toLowerCase()] ?? 'plain-text';
}

export function formatPreviewLabel(format: FilePreviewFormat): string {
  switch (format) {
    case 'markdown':
      return 'Markdown';
    case 'plain-text':
      return 'Plain text';
    default:
      return 'Unsupported';
  }
}
