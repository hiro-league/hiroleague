<script lang="ts">
  /**
   * People (Phase 6): one family list in the core, read by extensions such as HomeHiro.
   * Three tabs, each one job: People (the list), Roles (one role at a time: what it is for, who holds it, its rights)
   * and Compare (every role side by side, read only). The header holds the tabs, the tab's action and, on Roles and
   * Compare, which app is shown (or all); it stays at the top while the page scrolls.
   */
  import { Eye, Plus, UserPlus } from '@lucide/svelte';
  import { OWNER } from './state/roles-controller.svelte';
  import { page } from '$app/state';
  import PageHeader from '$kit/ui/page-header.svelte';
  import { ADMIN_PAGE_MAX_W } from '$lib/styling/admin-tokens';
  import { Button } from '$kit/components/ui/button/index.js';
  import ConfirmDialog from '$kit/ui/confirm-dialog.svelte';
  import { toast } from '$kit/ui/toast.svelte';
  import PersonDialog from './dialogs/PersonDialog.svelte';
  import SignInDialog from './dialogs/SignInDialog.svelte';
  import { createPeopleController } from './state/people-controller.svelte';
  import PeopleListCard from './view/PeopleListCard.svelte';
  import PageTabs from '$kit/ui/page-tabs.svelte';
  import NewRoleDialog from './dialogs/NewRoleDialog.svelte';
  import { createRolesController } from './state/roles-controller.svelte';
  import RolesView from './view/RolesView.svelte';
  import CompareView from './view/CompareView.svelte';
  import AppFilter from './view/AppFilter.svelte';
  import { Resource } from '$kit/state/resource.svelte';
  import { listDevices } from '$lib/api/devices';
  import { devicesOf } from '../devices/shared/device-people';

  // Phase 9a: an app's Edit link opens People → Roles at one role (?tab=roles&role=kid).
  const asked = page.url.searchParams;
  const ctrl = createPeopleController(toast.show);
  // A role added, renamed or removed changes the People tab's role names too.
  const roles = createRolesController(toast.show, () => ctrl.load(), asked.get('role'));
  // Permissions phase 3: each person's devices, beside their WhatsApp address
  const devices = new Resource(listDevices);

  type Tab = 'people' | 'roles' | 'compare';
  const TABS: Tab[] = ['people', 'roles', 'compare'];
  const askedTab = asked.get('tab');
  let tab = $state<Tab>(TABS.find((t) => t === askedTab) ?? 'people');
  const tabDescriptors = [
    { id: 'people' as const, label: 'People' },
    { id: 'roles' as const, label: 'Roles' },
    { id: 'compare' as const, label: 'Compare' }
  ];
  // "View as" the role shown on Roles: the admin's menu and tabs as its people see them (Permissions phase 2)
  const shownRole = $derived(roles.roles.find((r) => r.role_id === roles.role));
  // A role opened from Compare starts at the top of its rights, not where Compare was scrolled to.
  function openRole(roleId: string) {
    roles.role = roleId;
    tab = 'roles';
    window.scrollTo({ top: 0 });
  }
</script>

<section class={ADMIN_PAGE_MAX_W}>
  <PageHeader title="People">
    {#snippet tabs()}
      <PageTabs label="People sections" tabs={tabDescriptors} value={tab} onchange={(id) => (tab = id)} />
    {/snippet}
    {#snippet actions()}
      {#if tab === 'people'}
        <Button disabled={ctrl.busy} onclick={() => ctrl.openAdd()}>
          <UserPlus size={15} /> Add person
        </Button>
      {:else if tab === 'roles'}
        {#if shownRole && shownRole.role_id !== OWNER}
          <Button variant="outline" disabled={roles.busy} onclick={() => void roles.viewAs(shownRole)}>
            <Eye size={15} /> View as {shownRole.name}
          </Button>
        {/if}
        <Button variant="outline" disabled={roles.busy} onclick={() => (roles.newName = '')}>
          <Plus size={15} /> New role
        </Button>
      {/if}
    {/snippet}
    {#if tab !== 'people'}
      <AppFilter sources={roles.sources} value={roles.app} onchange={(next) => (roles.app = next)} />
    {/if}
  </PageHeader>

  {#if tab === 'roles'}
    <RolesView ctrl={roles} people={ctrl.people} rolesOf={ctrl.rolesOf} />
  {:else if tab === 'compare'}
    <CompareView ctrl={roles} onopen={openRole} />
  {:else}
    <PeopleListCard {ctrl} devicesOf={(personId) => devicesOf(devices.data ?? [], personId)} />
  {/if}
</section>

<PersonDialog {ctrl} />
<NewRoleDialog ctrl={roles} />
<ConfirmDialog
  open={roles.removeTarget !== null}
  onOpenChange={(next) => {
    if (!next) roles.removeTarget = null;
  }}
  title="Remove the role {roles.removeTarget?.name ?? ''}?"
  message="It goes from HiroLeague and every app. Nobody has it, so nobody loses access."
  confirmLabel="Remove"
  pending={roles.busy}
  onConfirm={() => void roles.submitRemove()}
/>
<SignInDialog {ctrl} />
<ConfirmDialog
  open={ctrl.removeTarget !== null}
  onOpenChange={(next) => {
    if (!next) ctrl.removeTarget = null;
  }}
  title="Remove {ctrl.removeTarget?.name ?? ''}?"
  message="They leave the family list, and HomeHiro stops knowing them as family."
  confirmLabel="Remove"
  pending={ctrl.busy}
  onConfirm={() => void ctrl.submitRemove()}
/>
<ConfirmDialog
  open={ctrl.removeSignInTarget !== null}
  onOpenChange={(next) => {
    if (!next) ctrl.removeSignInTarget = null;
  }}
  title="Take {ctrl.removeSignInTarget?.name ?? ''}'s sign-in away?"
  message="They are signed out now and can't sign in to the admin again until given a new sign-in."
  confirmLabel="Take it away"
  pending={ctrl.busy}
  onConfirm={() => void ctrl.submitRemoveSignIn()}
/>
