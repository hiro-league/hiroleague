/**
 * Feature-neutral byte-size formatting for dense admin UI (file/log sizes).
 *
 * Renders a raw byte count as `B` / `KB` / `MB` with one decimal place above 1 KB.
 */

export function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}
