/** Drag-preview ghost for reordering catalog model ids (native HTML DnD drag image). */
export function createCatalogModelDragGhost(
  canonicalId: string,
  displayName: string | undefined
): HTMLDivElement {
  const ghost = document.createElement('div');
  ghost.className =
    'fixed z-[9999] max-w-sm rounded-lg border-2 border-primary bg-popover px-4 py-3 shadow-2xl pointer-events-none select-none';
  ghost.style.left = '-9999px';
  ghost.style.top = '0';
  const idEl = document.createElement('div');
  idEl.className = 'font-mono text-base font-semibold leading-snug text-foreground';
  idEl.textContent = canonicalId;
  ghost.appendChild(idEl);
  if (displayName) {
    const nameEl = document.createElement('div');
    nameEl.className = 'mt-1 font-sans text-sm text-muted-foreground';
    nameEl.textContent = displayName;
    ghost.appendChild(nameEl);
  }
  document.body.appendChild(ghost);
  return ghost;
}
