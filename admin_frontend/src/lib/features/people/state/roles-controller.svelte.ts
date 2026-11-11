import {
  addRole,
  listAccess,
  removeRole,
  renameRole,
  setRoleRights,
  setRoleSays,
  type AccessFeature,
  type AccessSource,
  type RoleAccess
} from '$lib/api/people';
import type { Notify } from '$kit/ui/toast.svelte';

export type RolesController = ReturnType<typeof createRolesController>;

export const ALL_SOURCES = 'all';
export const ALL_ROLES = 'all';
export const OWNER = 'owner';
const SEE = 'see';

export const rightKey = (feature: string, right: string) => `${feature}.${right}`;

/**
 * People → Roles (Phase 9a): what each role may do, per source — HiroLeague itself and each extension, which
 * declares its features and their rights when it connects. A role has each right or not; the owner has every
 * right except features not made for the owner. Each change saves at once (the extension is told and follows).
 */
export function createRolesController(notify: Notify, onRolesChanged: () => Promise<void>) {
  let sources = $state<AccessSource[]>([]);
  let roles = $state<RoleAccess[]>([]);
  let loading = $state(true);
  let busy = $state(false);
  let error = $state<string | null>(null);

  let tab = $state<string>(ALL_ROLES);
  let sourceId = $state<string>(ALL_SOURCES);

  /** The new-role dialog: null = closed. */
  let newName = $state<string | null>(null);
  let removeTarget = $state<RoleAccess | null>(null);

  async function load() {
    loading = true;
    error = null;
    try {
      const data = (await listAccess());
      sources = data.sources;
      roles = data.roles;
      if (tab !== ALL_ROLES && !roles.some((r) => r.role_id === tab)) tab = ALL_ROLES;
      if (sourceId !== ALL_SOURCES && !sources.some((s) => s.id === sourceId)) sourceId = ALL_SOURCES;
    } catch (err) {
      error = err instanceof Error ? err.message : "Failed to load what each role may do.";
    } finally {
      loading = false;
    }
  }

  async function run(what: string, call: () => Promise<unknown>, done?: string) {
    busy = true;
    try {
      await call();
      if (done) notify('success', done);
      await load();
      await onRolesChanged();
    } catch (err) {
      notify('error', err instanceof Error ? err.message : `${what} failed.`);
    } finally {
      busy = false;
    }
  }

  function granted(role: RoleAccess, source: AccessSource): Set<string> {
    return new Set(role.rights[source.id] ?? []);
  }

  /** Tick or untick one right; ticking adds See, unticking See takes the feature's other rights away. */
  function toggle(role: RoleAccess, source: AccessSource, feature: AccessFeature, right: string, on: boolean) {
    const next = granted(role, source);
    const key = rightKey(feature.id, right);
    if (on) {
      next.add(key);
      if (feature.rights.some((r) => r.id === SEE)) next.add(rightKey(feature.id, SEE));
    } else {
      next.delete(key);
      if (right === SEE) for (const k of [...next]) if (k.startsWith(`${feature.id}.`)) next.delete(k);
    }
    void run('Saving the rights', () => setRoleRights(role.role_id, source.id, [...next]));
  }

  function saveSays(role: RoleAccess, says: string) {
    if (says.trim() === role.says) return;
    void run('Saving the line', () => setRoleSays(role.role_id, says), `Saved what ${role.name} is for.`);
  }

  function rename(role: RoleAccess, name: string) {
    if (!name.trim() || name.trim() === role.name) return;
    void run('Renaming', () => renameRole(role.role_id, name), `Renamed to ${name.trim()}.`);
  }

  async function submitNew() {
    if (newName === null) return;
    const name = newName;
    busy = true;
    try {
      const role = (await addRole(name)).role;
      notify('success', `Added the role ${role.name}.`);
      newName = null;
      await load();
      await onRolesChanged();
      tab = role.role_id;
    } catch (err) {
      notify('error', err instanceof Error ? err.message : 'Adding the role failed.');
    } finally {
      busy = false;
    }
  }

  async function submitRemove() {
    if (!removeTarget) return;
    const role = removeTarget;
    removeTarget = null;
    await run('Removing the role', () => removeRole(role.role_id), `Removed ${role.name}.`);
    tab = ALL_ROLES;
  }

  return {
    load,
    toggle,
    saveSays,
    rename,
    submitNew,
    submitRemove,
    granted,
    get sources() {
      return sources;
    },
    get roles() {
      return roles;
    },
    get loading() {
      return loading;
    },
    get busy() {
      return busy;
    },
    get error() {
      return error;
    },
    get tab() {
      return tab;
    },
    set tab(value: string) {
      tab = value;
    },
    get sourceId() {
      return sourceId;
    },
    set sourceId(value: string) {
      sourceId = value;
    },
    get newName() {
      return newName;
    },
    set newName(value: string | null) {
      newName = value;
    },
    get removeTarget() {
      return removeTarget;
    },
    set removeTarget(value: RoleAccess | null) {
      removeTarget = value;
    }
  };
}
