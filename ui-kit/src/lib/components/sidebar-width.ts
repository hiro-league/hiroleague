// How wide the side menu may be, in pixels: dragged by its edge (sidebar-resize.svelte), kept in this browser.
// A little wider than shadcn's 16rem by default, so a page's tab icons fit on its row.
export const SIDEBAR_DEFAULT = 272;
export const SIDEBAR_MIN = 240;
export const SIDEBAR_MAX = 480;

/** A width the menu can take: whole pixels, between the narrowest and the widest. */
export const clampWidth = (px: number) => Math.round(Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, px)));

/** A saved width is used only when it is a number the menu can take as it is. */
export const isWidth = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v) && clampWidth(v) === v;
