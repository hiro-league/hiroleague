// mockup (Installing apps, phase 5, task 6): what the core's installs add to the Extensions page, as mock data until
// the backend serves it. Nothing here reaches the core.
import type { ExtensionRow } from '$lib/api/extensions';

export type InstallState = 'running' | 'stopped' | 'upgrading' | 'waiting' | 'failed';

/** A setting the app still needs before it works fully (its `extension.setup` items not done), with its page. */
export type SetupLeft = { title: string; link: string };

/** An app the core installed, as the page will read it. */
export type InstallInfo = {
  key: string;
  version: string;
  previous: string;
  port: number;
  state: InstallState;
  /** What it does now, or why it failed. */
  step: string;
  folder: string;
  data: string;
  /** A newer package of it in the Hiro home's packages folder, offered as an upgrade. */
  offered: string;
};

/** A package in the Hiro home's packages folder that isn't installed yet. */
export type PackageOffer = { file: string; key: string; title: string; version: string };

export const MOCK_HOME = 'C:\\ProgramData\\HiroLeague';

/** Hello, as an installed app's row (the list's own shape). */
export const MOCK_HELLO: ExtensionRow = {
  extension_id: 'mockup-example-hello',
  name: 'example.hello',
  label: 'Hello',
  kind: 'app',
  version: '0.1.0',
  description: 'The test app the core installs, upgrades and removes',
  paired_at: '2026-11-26T15:55:08Z',
  last_seen: '2026-11-26T15:55:08Z',
  relays_chat: false,
  started_by_core: false,
  enabled: null,
  mandatory: false,
  has_settings: false,
  pairing: '',
  site: 'http://example-hello.hiro.local',
  offers: [],
  uses: [],
  connected: true,
  connected_at: '2026-11-26T15:55:08Z',
  remote: '127.0.0.1',
  linked: null,
  account: '',
  pending: false,
  waits: false,
  waiting_count: 0
};

export const MOCK_INSTALLS: Record<string, InstallInfo> = {
  'example.hello': {
    key: 'example.hello',
    version: '0.1.0',
    previous: '',
    port: 8190,
    state: 'running',
    step: '',
    folder: `${MOCK_HOME}\\apps\\example.hello`,
    data: `${MOCK_HOME}\\apps\\example.hello\\data`,
    offered: '0.1.1'
  }
};

/** What each app still needs set (by the app's name). */
export const MOCK_SETUP_LEFT: Record<string, SetupLeft[]> = {
  'example.hello': [{ title: 'Pick who it greets', link: 'http://example-hello.hiro.local/settings' }],
  home: [
    { title: 'Connect Home Assistant', link: 'http://home.hiro.local/settings?tab=ha' },
    { title: 'Pick the rooms', link: 'http://home.hiro.local/settings?tab=rooms' }
  ]
};

export const MOCK_PACKAGES: PackageOffer[] = [
  { file: 'acme-notes-0.2.0.zip', key: 'acme.notes', title: 'Notes', version: '0.2.0' }
];

/** An upgrade's steps, as the core records them. */
export const UPGRADE_STEPS = [
  'Unpacking the new release',
  'Trying its migrations on a copy',
  'Switching to the new release',
  'Checking the new version answers'
] as const;

export function installCommand(file: string): string {
  return `hiro extension install "${MOCK_HOME}\\packages\\${file}"`;
}

export function removeCommand(key: string, purge: boolean): string {
  return `hiro extension remove ${key}${purge ? ' --purge' : ''}`;
}

/** The words of an install's state in the Status column. */
export function stateLine(info: InstallInfo): { tone: 'ok' | 'off' | 'warn' | 'error' | 'info'; text: string } {
  switch (info.state) {
    case 'running':
      return { tone: 'ok', text: 'Running' };
    case 'stopped':
      return { tone: 'off', text: 'Stopped' };
    case 'upgrading':
      return { tone: 'info', text: `Upgrading: ${info.step}` };
    case 'waiting':
      return { tone: 'warn', text: 'Waiting to pair' };
    case 'failed':
      return { tone: 'error', text: `Failed: ${info.step}` };
  }
}
