// mockup (Installing apps, phase 5, task 6): the page's installed-app parts on mock data: start and stop, an upgrade
// that walks its steps, and the install and remove commands to copy. Nothing reaches the core.
import { repeat } from '$kit/state/poll.svelte';
import type { ExtensionRow } from '$lib/api/extensions';
import {
  MOCK_INSTALLS,
  MOCK_PACKAGES,
  MOCK_SETUP_LEFT,
  UPGRADE_STEPS,
  installCommand,
  removeCommand,
  type InstallInfo,
  type PackageOffer,
  type SetupLeft
} from './installed';

export type InstallsMock = ReturnType<typeof createInstallsMock>;

export function createInstallsMock() {
  let installs = $state<Record<string, InstallInfo>>(structuredClone(MOCK_INSTALLS));
  /** The upgrade dialog: the app it upgrades, the step reached (-1: not started), and how it ended. */
  let upgrade = $state<{ key: string; to: string; step: number; done: boolean } | null>(null);
  let stopUpgrade: (() => void) | null = null;
  /** The command dialog: installing a package, or removing an installed app. */
  let command = $state<{ title: string; lines: string[] } | null>(null);
  let copied = $state(false);

  const installOf = (row: ExtensionRow): InstallInfo | null => installs[row.name] ?? null;

  function startUpgrade() {
    if (!upgrade) return;
    const key = upgrade.key;
    upgrade.step = 0;
    installs[key] = { ...installs[key], state: 'upgrading', step: UPGRADE_STEPS[0] };
    stopUpgrade = repeat(() => {
      if (!upgrade) return;
      if (upgrade.step < UPGRADE_STEPS.length - 1) {
        upgrade.step += 1;
        installs[key] = { ...installs[key], step: UPGRADE_STEPS[upgrade.step] };
        return;
      }
      stopUpgrade?.();
      upgrade.done = true;
      installs[key] = { ...installs[key], state: 'running', step: '', previous: installs[key].version,
                        version: upgrade.to, offered: '' };
    }, 2000);
  }

  return {
    installOf,
    byKey: (key: string): InstallInfo | null => installs[key] ?? null,
    setupLeft: (row: ExtensionRow): SetupLeft[] => MOCK_SETUP_LEFT[row.name] ?? [],
    packages: (): PackageOffer[] => MOCK_PACKAGES,
    toggle: (row: ExtensionRow) => {
      const info = installOf(row);
      if (!info) return;
      installs[row.name] = { ...info, state: info.state === 'running' ? 'stopped' : 'running' };
    },
    get upgrade() {
      return upgrade;
    },
    openUpgrade: (row: ExtensionRow) => {
      const info = installOf(row);
      if (info?.offered) upgrade = { key: info.key, to: info.offered, step: -1, done: false };
    },
    startUpgrade,
    closeUpgrade: () => {
      stopUpgrade?.();
      upgrade = null;
    },
    get command() {
      return command;
    },
    get copied() {
      return copied;
    },
    openInstall: () => {
      copied = false;
      command = {
        title: 'Install an app',
        lines: MOCK_PACKAGES.map((p) => installCommand(p.file))
      };
    },
    openRemove: (row: ExtensionRow) => {
      copied = false;
      command = {
        title: `Remove ${row.label}`,
        lines: [removeCommand(row.name, false), removeCommand(row.name, true)]
      };
    },
    copy: async (line: string) => {
      await navigator.clipboard.writeText(line);
      copied = true;
    },
    closeCommand: () => {
      command = null;
    }
  };
}
