import { untrack } from 'svelte';
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
import { Action } from '$kit/state/action.svelte';
import { Resource } from '$kit/state/resource.svelte';
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
export function createRolesController(
  notify: Notify,
  onRolesChanged: () => Promise<void>,
  /** The role to show first (an app's Edit link), if it exists once the roles are read. */
  firstRole: string | null = null
) {
  const access = new Resource(listAccess);
  const sources = $derived(access.data?.sources ?? []);
  const roles = $derived(access.data?.roles ?? []);
  const work = new Action();

  let tab = $state<string>(ALL_ROLES);
  let sourceId = $state<string>(ALL_SOURCES);

  // A tab or source that is gone after a read falls back to "all"; the first read opens `firstRole`.
  let first = true;
  $effect(() => {
    const data = access.data;
    if (!data) return;
    untrack(() => {
      if (first) {
        first = false;
        if (firstRole && data.roles.some((r) => r.role_id === firstRole)) tab = firstRole;
      }
      if (tab !== ALL_ROLES && !data.roles.some((r) => r.role_id === tab)) tab = ALL_ROLES;
      if (sourceId !== ALL_SOURCES && !data.sources.some((s) => s.id === sourceId)) sourceId = ALL_SOURCES;
    });
  });

  /** The new-role dialog: null = closed. */
  let newName = $state<string | null>(null);
  let removeTarget = $state<RoleAccess | null>(null);

  async function run(call: () => Promise<unknown>, done?: string) {
    await work.run(async () => {
      await call();
      if (done) notify('success', done);
      await access.reload();
      await onRolesChanged();
    });
    if (work.error) notify('error', work.error);
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
    void run(() => setRoleRights(role.role_id, source.id, [...next]));
  }

  function saveSays(role: RoleAccess, says: string) {
    if (says.trim() === role.says) return;
    void run(() => setRoleSays(role.role_id, says), `Saved what ${role.name} is for.`);
  }

  function rename(role: RoleAccess, name: string) {
    if (!name.trim() || name.trim() === role.name) return;
    void run(() => renameRole(role.role_id, name), `Renamed to ${name.trim()}.`);
  }

  async function submitNew() {
    if (newName === null) return;
    const name = newName;
    await work.run(async () => {
      const role = (await addRole(name)).role;
      notify('success', `Added the role ${role.name}.`);
      newName = null;
      await access.reload();
      await onRolesChanged();
      tab = role.role_id;
    });
    if (work.error) notify('error', work.error);
  }

  async function submitRemove() {
    if (!removeTarget) return;
    const role = removeTarget;
    removeTarget = null;
    await run(() => removeRole(role.role_id), `Removed ${role.name}.`);
    tab = ALL_ROLES;
  }

  return {
    load: access.reload,
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
      return access.data === null && !access.error;
    },
    get busy() {
      return work.busy;
    },
    get error() {
      return access.error || null;
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
