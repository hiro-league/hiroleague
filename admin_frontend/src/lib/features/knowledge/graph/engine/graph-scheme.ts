/**
 * Dark/light-mode-aware colour scheme for the knowledge graph canvas.
 *
 * The app sets `data-theme="dark"` / `"light"` on <html> (shell-preferences →
 * document.documentElement.dataset.theme). The engine caches one Scheme and refreshes it
 * only on a theme toggle (MutationObserver), instead of reading the DOM + allocating a
 * fresh object inside every node/edge draw callback (thousands of times/sec at 60fps).
 */

export type Scheme = {
  /** node name pill background */
  pillBg: string;
  /** node name pill text */
  nodeText: string;
  /** edge label text */
  edgeText: string;
  /** edge label pill background (matches the canvas --background so the label masks the line) */
  edgePillBg: string;
  /** edge line color */
  linkColor: string;
  /** edge line color for non-matches in "dim" search-focus mode */
  linkColorDim: string;
  /** invalid/superseded edge line color (drawn dashed) */
  edgeInvalid: string;
  /** search-highlight ring/stroke (amber, semi-transparent) */
  matchRing: string;
  /** selection ring/stroke (blue) for the clicked node/edge — overrides the search highlight */
  selectRing: string;
  // "Just added/updated" flash colors as "r,g,b" (alpha applied per-frame as the glow
  // fades). Tuned to pop against every node-type disc color in both themes.
  /** bright ring stroke around fresh nodes + the fresh-edge overlay */
  glowRingRGB: string;
  /** soft filled halo behind fresh nodes */
  glowFillRGB: string;
};

export function computeScheme(): Scheme {
  const dark =
    typeof document !== 'undefined' && document.documentElement.dataset.theme === 'dark';
  return dark
    ? {
        pillBg: 'rgba(2,6,23,0.72)',
        nodeText: 'rgba(226,232,240,0.95)',
        edgeText: 'rgba(226,232,240,0.5)',
        // Edge-label pill — same colour as the canvas --background (#15100f) so it masks the line
        // behind the text. The LAST value is the transparency: 1 = opaque; lower it (e.g. 0.7) to
        // let the edge line bleed through the pill.
        edgePillBg: 'rgba(21,16,15,0.8)',
        linkColor: 'rgba(148,163,184,0.28)',
        linkColorDim: 'rgba(148,163,184,0.07)', // dimmed non-matches
        edgeInvalid: 'rgba(248,113,113,0.25)', // red-400 — superseded facts (dashed)
        matchRing: 'rgba(251,191,36,0.6)', // amber-400, semi-transparent — pops but soft on dark
        selectRing: 'rgba(59,130,246,0.95)', // blue-500 — selected node/edge (distinct from amber)
        glowRingRGB: '110,231,183', // emerald-300 — bright on dark
        glowFillRGB: '52,211,153' // emerald-400
      }
    : {
        pillBg: 'rgba(255,255,255,0.72)',
        nodeText: 'rgba(15,23,42,0.92)',
        edgeText: 'rgba(30,41,59,0.5)',
        // Edge-label pill — same colour as the canvas --background (#fff6f5). Last value = alpha
        // (1 = opaque; lower to let the line show through).
        edgePillBg: 'rgba(255,246,245,1)',
        linkColor: 'rgba(148,163,184,0.25)',
        linkColorDim: 'rgba(148,163,184,0.08)', // dimmed non-matches
        edgeInvalid: 'rgba(220,38,38,0.3)', // red-600 — superseded facts (dashed)
        matchRing: 'rgba(217,119,6,0.7)', // amber-600, semi-transparent — readable on light
        selectRing: 'rgba(37,99,235,0.95)', // blue-600 — selected node/edge
        glowRingRGB: '5,150,105', // emerald-600 — saturated, reads on white
        glowFillRGB: '16,185,129' // emerald-500
      };
}
