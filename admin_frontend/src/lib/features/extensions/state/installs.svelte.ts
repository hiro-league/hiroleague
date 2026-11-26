// The Extensions page's installed apps (Installing apps, phase 5): their install facts from the list, what each
// connected app still needs set, the packages waiting in the Hiro home, start and stop, an upgrade the page follows to
// its end, and the commands to install or remove one (they need an administrator, so the page gives the commands).
import {
  getPackages,
  getRemoveCommands,
  getSetup,
  getUpgrade,
  startInstalled,
  startUpgrade,
  stopInstalled,
  type ExtensionRow,
  type InstallRow,
  type PackageOffer,
  type SetupLeft,
  type UpgradeState
} from '$lib/api/extensions';
import { KeyedAction } from '$kit/state/keyed-action.svelte';
import { repeat } from '$kit/state/poll.svelte';
import { Resource } from '$kit/state/resource.svelte';
import type { Notify } from '$kit/ui/toast.svelte';
import { errorMessage } from '$kit/api/client';
import { installLine, setupHref, upgradeOffer, type StatusTone } from '../shared/installs';

export type Installs = ReturnType<typeof createInstalls>;

/** `installs` is the list's (read again every 5 s); `reload` reads the list again. */
export function createInstalls(installs: () => InstallRow[], reload: () => Promise<void>, notify: Notify) {
  // Asked as the page opens: each connected app answers what it still needs set; read again with Reload
  const setup = new Resource((signal) => getSetup(signal));
  const packages = new Resource((signal) => getPackages(signal));
  const switching = new KeyedAction();

  let upgrade = $state<{ row: ExtensionRow; offer: PackageOffer; state: UpgradeState | null; error: string } | null>(null);
  let stopFollowing: (() => void) | null = null;
  let command = $state<{ title: string; lines: string[]; note: string } | null>(null);
  let copied = $state('');

  const installOf = (row: ExtensionRow): InstallRow | null => installs().find((i) => i.key === row.name) ?? null;

  async function follow(key: string) {
    if (!upgrade) return;
    try {
      upgrade.state = await getUpgrade(key);
    } catch (e) {
      upgrade.error = errorMessage(e);
    }
    if (upgrade && upgrade.state && !upgrade.state.running) {
      stopFollowing?.();
      stopFollowing = null;
      await Promise.all([reload(), packages.reload()]);
    }
  }

  return {
    installOf,
    line: (row: ExtensionRow): { tone: StatusTone; text: string } | null => {
      const info = installOf(row);
      return info ? installLine(info) : null;
    },
    setupLeft: (row: ExtensionRow): SetupLeft[] => setup.data?.left[row.extension_id] ?? [],
    setupError: (row: ExtensionRow): string => setup.data?.errors[row.extension_id] ?? '',
    href: (row: ExtensionRow, item: SetupLeft) => setupHref(row, item),
    upgradeOffer: (row: ExtensionRow): PackageOffer | null => {
      const info = installOf(row);
      return info ? upgradeOffer(packages.data?.packages ?? [], info) : null;
    },
    get packages() {
      return packages;
    },
    reloadSetup: () => setup.reload(),
    isSwitching: (row: ExtensionRow) => switching.busy(row.name),
    /** Start a stopped app, stop a running one, with the core's own right; the list shows the result. */
    toggle: (row: ExtensionRow) => {
      const info = installOf(row);
      if (!info) return;
      void switching.run(row.name, async () => {
        await (info.running ? stopInstalled(info.key) : startInstalled(info.key));
        await reload();
      }).then(() => {
        const failed = switching.error(row.name);
        if (failed) notify('error', failed);
      });
    },
    get upgrade() {
      return upgrade;
    },
    openUpgrade: (row: ExtensionRow, offer: PackageOffer) => {
      upgrade = { row, offer, state: null, error: '' };
    },
    /** Start the upgrade, then follow it until it ends (the list follows its step too). */
    runUpgrade: async () => {
      if (!upgrade) return;
      try {
        upgrade.state = await startUpgrade(upgrade.offer.key, upgrade.offer.file);
      } catch (e) {
        upgrade.error = errorMessage(e);
        return;
      }
      const key = upgrade.offer.key;
      stopFollowing = repeat(() => follow(key), 1500);
    },
    closeUpgrade: () => {
      stopFollowing?.();
      stopFollowing = null;
      upgrade = null;
    },
    get command() {
      return command;
    },
    get copied() {
      return copied;
    },
    openInstall: () => {
      copied = '';
      const offers = (packages.data?.packages ?? []).filter((p) => p.offer === 'install');
      command = {
        title: 'Install an app',
        lines: offers.map((p) => p.command),
        note: offers.length
          ? ''
          : `No package waits to be installed: put one in ${packages.data?.folder ?? "the Hiro home's packages folder"}.`
      };
    },
    openRemove: async (row: ExtensionRow) => {
      copied = '';
      try {
        const lines = await getRemoveCommands(row.name);
        command = { title: `Remove ${row.label}`, lines: [lines.remove, lines.purge], note: '' };
      } catch (e) {
        notify('error', errorMessage(e));
      }
    },
    copy: async (line: string) => {
      await navigator.clipboard.writeText(line);
      copied = line;
    },
    closeCommand: () => {
      command = null;
    }
  };
}
