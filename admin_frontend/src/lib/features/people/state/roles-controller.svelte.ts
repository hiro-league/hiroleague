import { untrack } from 'svelte';
import {
  addRole,
  getRoleAdminView,
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
import { menuPreview } from '$lib/shell/menu-preview.svelte';
import { featureOfKey, reachOf, setReach, withReaches, type Reach } from '../reach';


export type RolesController = ReturnType<typeof createRolesController>;

export const OWNER = 'owner';
export const ALL_APPS = 'all';
const SEE = 'see';

export const rightKey = (feature: string, right: string) => `${feature}.${right}`;

/**
 * People → Roles and Compare (Phase 9a; Permissions phase 1): what each role may do, per source — HiroLeague itself
 * and each extension, which declares its features and their rights when it connects. A role has each right or not
 * (or, for a right about people's things, their own or everyone's); the owner has every right except features not
 * made for the owner. Each change saves at once (the extension is told and follows).
 *
 * `role` is the role shown on Roles; `app` the source both tabs show, or ALL_APPS.
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

  let role = $state<string>(firstRole ?? '');
  let app = $state<string>(ALL_APPS);
  const shown = $derived(app === ALL_APPS ? sources : sources.filter((s) => s.id === app));

  // A role that is gone after a read (or none yet) falls back to the first one that isn't the owner; an app that is
  // gone falls back to all.
  $effect(() => {
    const data = access.data;
    if (!data) return;
    untrack(() => {
      if (!data.roles.some((r) => r.role_id === role)) role = (data.roles.find((r) => r.role_id !== OWNER) ?? data.roles[0])?.role_id ?? '';
      if (app !== ALL_APPS && !data.sources.some((s) => s.id === app)) app = ALL_APPS;
    });
  });

  /** How far a role's grant of one right reaches: a right not about people's things is everyone's or nothing. */
  function reach(role: RoleAccess, source: AccessSource, feature: AccessFeature, right: string): Reach {
    return reachOf(granted(role, source), rightKey(feature.id, right));
  }

  function reaches(role: RoleAccess, source: AccessSource, feature: AccessFeature): Record<string, Reach> {
    return Object.fromEntries(feature.rights.map((r) => [r.id, reach(role, source, feature, r.id)]));
  }

  /** Set a personal right's reach and save it at once; See follows (setReach), and the core keeps it as it says. */
  function setRightReach(role: RoleAccess, source: AccessSource, feature: AccessFeature, right: string, to: Reach) {
    const next = setReach(feature.rights, reaches(role, source, feature), right, to);
    saveRights(role, source, withReaches(granted(role, source), feature.id, next));
  }

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

  /** Save a role's keys in one source at once; the app follows. */
  function saveRights(role: RoleAccess, source: AccessSource, keys: string[]) {
    void run(() => setRoleRights(role.role_id, source.id, keys));
  }

  /** "View as": the admin's menu and tabs as this role's people see them, from the levels the core works out. */
  async function viewAs(role: RoleAccess) {
    await work.run(async () => {
      menuPreview.start(role.name, (await getRoleAdminView(role.role_id)).levels);
    });
    if (work.error) notify('error', work.error);
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
      // a fix: by prefix, unticking `logs`'s See also took `logs.runs` and `logs.usage` away
      if (right === SEE) for (const k of [...next]) if (featureOfKey(k) === feature.id) next.delete(k);
    }
    saveRights(role, source, [...next]);
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
      const added = (await addRole(name)).role;
      notify('success', `Added the role ${added.name}.`);
      newName = null;
      await access.reload();
      await onRolesChanged();
      role = added.role_id;
    });
    if (work.error) notify('error', work.error);
  }

  async function submitRemove() {
    if (!removeTarget) return;
    const role = removeTarget;
    removeTarget = null;
    await run(() => removeRole(role.role_id), `Removed ${role.name}.`);
  }

  return {
    load: access.reload,
    toggle,
    saveSays,
    rename,
    submitNew,
    submitRemove,
    granted,
    viewAs,
    reach,
    reaches,
    setRightReach,
    personal: (_source: AccessSource, feature: AccessFeature, right: string) =>
      feature.rights.some((r) => r.id === right && r.personal),
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
    /** The role shown on Roles. */
    get role() {
      return role;
    },
    set role(value: string) {
      role = value;
    },
    /** The app picked in the filter, or ALL_APPS. */
    get app() {
      return app;
    },
    set app(value: string) {
      app = value;
    },
    /** The sources the filter lets through, in their order. */
    get shown() {
      return shown;
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
