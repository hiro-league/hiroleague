// The installed apps' rules (Installing apps, phase 5): what the Status column says, which package offers an
// upgrade, where a setup item's link goes, and the row of an install that hasn't paired yet. Pure.
import type { ExtensionRow, InstallRow, PackageOffer, SetupLeft } from '$lib/api/extensions';

export type StatusTone = 'ok' | 'off' | 'warn' | 'error' | 'info';

/** The Status column for an installed app: its service and its install's state. */
export function installLine(info: InstallRow): { tone: StatusTone; text: string } {
  switch (info.state) {
    case 'upgrading':
      return { tone: 'info', text: `Upgrading: ${info.step}` };
    case 'failed':
      return { tone: 'error', text: `Failed: ${info.step}` };
    case 'waiting':
      return { tone: 'warn', text: 'Waiting to pair' };
    case 'approving':
      return { tone: 'warn', text: 'Waiting for its admin step' };
    case 'removing':
      return { tone: 'off', text: 'Being removed' };
    default:
      if (info.running === null) return { tone: 'warn', text: 'No service on this machine' };
      return info.running ? { tone: 'ok', text: 'Running' } : { tone: 'off', text: 'Stopped' };
  }
}

function numbers(version: string): number[] {
  return (version.match(/^\d+(?:\.\d+)*/)?.[0] ?? '0').split('.').map(Number);
}

/** -1, 0 or 1 as `a` is older, the same or newer than `b` (their release numbers). */
export function compareVersions(a: string, b: string): number {
  const x = numbers(a);
  const y = numbers(b);
  for (let i = 0; i < Math.max(x.length, y.length); i++) {
    const d = (x[i] ?? 0) - (y[i] ?? 0);
    if (d) return Math.sign(d);
  }
  return 0;
}

/** The newest package that upgrades this install, or null (only a running install upgrades). */
export function upgradeOffer(packages: PackageOffer[], info: InstallRow): PackageOffer | null {
  if (info.state !== 'running') return null;
  const newer = packages.filter((p) => p.key === info.key && compareVersions(p.version, info.version) > 0);
  return newer.sort((a, b) => compareVersions(b.version, a.version))[0] ?? null;
}

/** Where a setup item's link goes: the app's own site (its address) and the item's page; the admin's page when the
 * item names no app. */
export function setupHref(row: ExtensionRow, item: SetupLeft): string {
  if (!item.app) return item.path;
  const site = item.app === row.name ? row.site : '';
  return site ? `${site.replace(/\/$/, '')}${item.path}` : '';
}

/** The row of an install with no extension behind it yet (it hasn't paired, or it failed first). */
export function installAsRow(info: InstallRow): ExtensionRow {
  return {
    extension_id: `install:${info.key}`,
    name: info.key,
    label: info.title,
    kind: 'app',
    version: info.version,
    description: '',
    paired_at: null,
    last_seen: null,
    relays_chat: false,
    started_by_core: false,
    enabled: null,
    mandatory: false,
    has_settings: false,
    pairing: '',
    site: '',
    offers: [],
    uses: [],
    connected: false,
    connected_at: null,
    remote: null,
    linked: null,
    account: '',
    pending: false,
    waits: false,
    waiting_count: 0
  };
}

/** An install's row has no extension in the core yet: no Permissions, no test call, no pairing again. */
export const isInstallOnly = (row: ExtensionRow) => row.extension_id.startsWith('install:');

/** The installs with no extension row of their own, as rows of the one list. */
export function unpairedInstalls(installs: InstallRow[], rows: ExtensionRow[]): ExtensionRow[] {
  const names = new Set(rows.map((r) => r.name));
  return installs.filter((i) => !names.has(i.key)).map(installAsRow);
}
