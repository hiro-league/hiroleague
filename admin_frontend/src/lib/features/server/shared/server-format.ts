/**
 * Pure formatting/URL helpers shared by the Workspaces and Gateways tabs.
 *
 * Extracted from the two tab components (which previously each carried byte-for-byte
 * copies) so the logic has one home and can be unit-tested.
 */
import { formatBytes } from '$lib/format/bytes';

/** Compact "Mon D, h:mm AM" stamp for a stderr-log mtime; `''` when missing/invalid. */
export function formatStderrTime(value: string | null): string {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit'
  });
}

/** Hover title for a stderr-log button: name, last-updated time (if any), and size. */
export function stderrTitle(mtime: string | null, size: number): string {
  const updated = formatStderrTime(mtime);
  return `stderr.log${updated ? ` updated ${updated}` : ''} (${formatBytes(size)})`;
}

/** Convert a gateway `ws(s)://` URL to its browser-openable `http(s)://` form. */
export function gatewayHttpUrl(url: string | null): string | null {
  if (!url) return null;
  return url.replace(/^wss:/i, 'https:').replace(/^ws:/i, 'http:');
}

/** Local status endpoint for a workspace's HTTP port. */
export function statusUrl(httpPort: number): string {
  return `http://127.0.0.1:${httpPort}/status`;
}

/** Local admin UI URL for a workspace's admin port. */
export function adminUrl(adminPort: number): string {
  return `http://127.0.0.1:${adminPort}/`;
}
