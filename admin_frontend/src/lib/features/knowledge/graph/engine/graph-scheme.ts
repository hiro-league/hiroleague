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
  /** edge label text (drawn directly on the edge, no pill bg) */
  edgeText: string;
  /** edge line color */
  linkColor: string;
  /** edge line color for non-matches in "dim" search-focus mode */
  linkColorDim: string;
  /** search-highlight ring/stroke (amber, semi-transparent) */
  matchRing: string;
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
        // Stronger edge text (lighter + opaque) since it sits on the line with no
        // pill; lines themselves are more transparent so labels stay readable.
        edgeText: 'rgba(226,232,240,1)',
        linkColor: 'rgba(148,163,184,0.28)',
        linkColorDim: 'rgba(148,163,184,0.07)', // dimmed non-matches
        matchRing: 'rgba(251,191,36,0.6)', // amber-400, semi-transparent — pops but soft on dark
        glowRingRGB: '110,231,183', // emerald-300 — bright on dark
        glowFillRGB: '52,211,153' // emerald-400
      }
    : {
        pillBg: 'rgba(255,255,255,0.72)',
        nodeText: 'rgba(15,23,42,0.92)',
        edgeText: 'rgba(30,41,59,1)',
        linkColor: 'rgba(148,163,184,0.25)',
        linkColorDim: 'rgba(148,163,184,0.08)', // dimmed non-matches
        matchRing: 'rgba(217,119,6,0.7)', // amber-600, semi-transparent — readable on light
        glowRingRGB: '5,150,105', // emerald-600 — saturated, reads on white
        glowFillRGB: '16,185,129' // emerald-500
      };
}
