/**
 * Pure canvas-drawing helpers for the knowledge graph engine: node-type icons, label
 * sizing, text pills, and name wrapping. No force-graph / DOM state — just functions the
 * engine's node/link draw callbacks call. Kept out of the engine so they stay testable.
 */
import { NODE_LABEL_MAX_LINES, NODE_LABEL_WRAP } from './graph-config';

// Lucide icon path data — 24×24 viewBox, drawn in white inside each colored disc.
// Hardcoded so the canvas render stays deterministic across platforms (emoji glyph
// rendering varies). Path strings come straight from lucide@0.x svgs.
type LucideIcon = {
  paths: string[];
  /** Optional circle parts as [cx, cy, r] in the 24×24 viewBox. */
  circles?: Array<[number, number, number]>;
};

const ICONS: Record<string, LucideIcon> = {
  Person: {
    paths: ['M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2'],
    circles: [[12, 7, 4]]
  },
  Place: {
    paths: ['M20 10c0 7-8 12-8 12s-8-5-8-12a8 8 0 0 1 16 0Z'],
    circles: [[12, 10, 3]]
  },
  Event: {
    paths: [
      'M8 2v4',
      'M16 2v4',
      'M3 10h18',
      'M3 4h18a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z'
    ]
  },
  Organization: {
    paths: ['M6 22V4a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v18Z', 'M10 6h4', 'M10 10h4', 'M10 14h4', 'M10 18h4']
  },
  Object: {
    paths: [
      'M21 8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16Z',
      'm3.3 7 8.7 5 8.7-5',
      'M12 22V12'
    ]
  },
  Entity: {
    paths: [],
    circles: [[12, 12, 8]]
  }
};

// PERF: `new Path2D(d)` parses the SVG path mini-language on construction, wasteful to
// redo for every icon path on every frame. Build each type's Path2D[] once (lazily —
// Path2D is browser-only) and reuse the cached objects in drawIcon.
const iconPath2DCache = new Map<string, Path2D[]>();
function iconPaths(type: string): Path2D[] {
  let cached = iconPath2DCache.get(type);
  if (!cached) {
    const icon = ICONS[type] ?? ICONS.Entity;
    cached = icon.paths.map((d) => new Path2D(d));
    iconPath2DCache.set(type, cached);
  }
  return cached;
}

/** Draw a white Lucide icon centered at (x, y), sized to `size` graph-space units. */
export function drawIcon(
  ctx: CanvasRenderingContext2D,
  type: string,
  x: number,
  y: number,
  size: number,
  scale: number
): void {
  const icon = ICONS[type] ?? ICONS.Entity;
  const s = size / 24;
  ctx.save();
  ctx.translate(x - size / 2, y - size / 2);
  ctx.scale(s, s);
  ctx.strokeStyle = 'rgba(255,255,255,0.95)';
  // Compensate so stroke renders at ≈1.8px on-screen regardless of zoom.
  ctx.lineWidth = 1.8 / (s * scale);
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  for (const p of iconPaths(type)) {
    ctx.stroke(p);
  }
  if (icon.circles) {
    for (const [cx, cy, r] of icon.circles) {
      ctx.beginPath();
      ctx.arc(cx, cy, r, 0, 2 * Math.PI);
      ctx.stroke();
    }
  }
  ctx.restore();
}

/**
 * Map the current zoom level to a canvas-space font size, or return null when the label
 * should be hidden. The returned value is already divided by `scale` so passing it to
 * ctx.font produces the configured on-screen pixel size.
 */
export function labelFontSize(
  scale: number,
  zoomMin: number,
  zoomMax: number,
  fontMin: number,
  fontMax: number
): number | null {
  if (scale < zoomMin) return null;
  const onScreen =
    scale >= zoomMax
      ? fontMax
      : fontMin + ((scale - zoomMin) / (zoomMax - zoomMin)) * (fontMax - fontMin);
  return onScreen / scale;
}

/**
 * Draw a centered text label. When bgColor is null the text is drawn directly (no pill
 * background). `radius` rounds the pill corners (0 = sharp rectangle); edge labels pass a
 * radius for a rounded pill, node labels keep the default sharp rect.
 */
export function drawTextPill(
  ctx: CanvasRenderingContext2D,
  text: string,
  cx: number,
  cy: number,
  fontSize: number,
  textColor: string,
  bgColor: string | null,
  radius = 0
): void {
  ctx.font = `${fontSize}px ui-sans-serif, system-ui, sans-serif`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  if (bgColor) {
    const m = ctx.measureText(text);
    const padX = fontSize * 0.35;
    const padY = fontSize * 0.18;
    const x = cx - m.width / 2 - padX;
    const y = cy - fontSize / 2 - padY;
    const w = m.width + 2 * padX;
    const h = fontSize + 2 * padY;
    ctx.fillStyle = bgColor;
    if (radius > 0 && typeof ctx.roundRect === 'function') {
      ctx.beginPath();
      ctx.roundRect(x, y, w, h, radius);
      ctx.fill();
    } else {
      ctx.fillRect(x, y, w, h);
    }
  }
  ctx.fillStyle = textColor;
  ctx.fillText(text, cx, cy);
}

/**
 * Wrap a node name onto multiple lines when it exceeds NODE_LABEL_WRAP chars. Word-aware,
 * with a hard break for single words longer than the limit; capped at NODE_LABEL_MAX_LINES
 * with an ellipsis on the last line if it overflows.
 */
export function wrapLabel(name: string): string[] {
  if (name.length <= NODE_LABEL_WRAP) return [name];
  const lines: string[] = [];
  let cur = '';
  const flush = () => {
    if (cur) lines.push(cur);
    cur = '';
  };
  for (const word of name.split(/\s+/)) {
    if (word.length > NODE_LABEL_WRAP) {
      flush();
      let rest = word;
      while (rest.length > NODE_LABEL_WRAP) {
        lines.push(rest.slice(0, NODE_LABEL_WRAP));
        rest = rest.slice(NODE_LABEL_WRAP);
      }
      cur = rest;
    } else if (!cur) {
      cur = word;
    } else if (`${cur} ${word}`.length <= NODE_LABEL_WRAP) {
      cur = `${cur} ${word}`;
    } else {
      flush();
      cur = word;
    }
  }
  flush();
  if (lines.length > NODE_LABEL_MAX_LINES) {
    const kept = lines.slice(0, NODE_LABEL_MAX_LINES);
    const last = kept[NODE_LABEL_MAX_LINES - 1];
    kept[NODE_LABEL_MAX_LINES - 1] = `${last.slice(0, NODE_LABEL_WRAP - 1)}…`;
    return kept;
  }
  return lines;
}
