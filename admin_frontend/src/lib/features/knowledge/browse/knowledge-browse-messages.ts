/** Toast copy for Knowledge browse bulk actions (pure helpers). */

export function knowledgeDeleteSuccessMessage(
  deleted: number,
  failed: number,
  singleTitle?: string
): string {
  if (failed > 0) {
    return `${deleted} document${deleted === 1 ? '' : 's'} removed; ${failed} failed.`;
  }
  if (deleted === 1 && singleTitle) {
    return `"${singleTitle}" removed from the knowledge index.`;
  }
  return `${deleted} documents removed from the knowledge index.`;
}

export function knowledgeMetadataSavedMessage(saved: number, failed: number): string {
  if (failed > 0) {
    return `${saved} document${saved === 1 ? '' : 's'} updated; ${failed} failed.`;
  }
  if (saved === 1) {
    return 'Document metadata updated.';
  }
  return `${saved} documents updated.`;
}
