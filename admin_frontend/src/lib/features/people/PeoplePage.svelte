<script lang="ts">
  /**
   * People (Phase 6): one family list in the core, read by extensions such as HomeHiro.
   * Phase 9a: two tabs — People (the list) and Roles (what each role may do in HiroLeague and each app).
   */
  import { onMount } from 'svelte';
  import { UserPlus } from '@lucide/svelte';
  import { page } from '$app/state';
  import PageHeader from '$kit/ui/page-header.svelte';
  import { ADMIN_PAGE_MAX_W } from '$lib/styling/admin-tokens';
  import Panel from '$kit/ui/panel.svelte';
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
  import RolesTab from './view/RolesTab.svelte';

  const ctrl = createPeopleController(toast.show);
  // A role added, renamed or removed changes the People tab's role names too.
  const roles = createRolesController(toast.show, () => ctrl.load());

  // Phase 9a: an app's Edit link opens People → Roles at one role (?tab=roles&role=kid).
  const asked = page.url.searchParams;
  let tab = $state<'people' | 'roles'>(asked.get('tab') === 'roles' ? 'roles' : 'people');
  const tabDescriptors = [
    { id: 'people' as const, label: 'People' },
    { id: 'roles' as const, label: 'Roles' }
  ];

  onMount(() => {
    void ctrl.load();
    void roles.load().then(() => {
      const role = asked.get('role');
      if (role && roles.roles.some((r) => r.role_id === role)) roles.tab = role;
    });
  });
</script>

<section class={ADMIN_PAGE_MAX_W}>
  <PageHeader title="People" description="The family: who they are, what Hiro calls them, how to reach them, their role. HomeHiro reads this list.">
    {#snippet tabs()}
    <PageTabs label="People sections" tabs={tabDescriptors} value={tab} onchange={(id) => (tab = id)} />
    {/snippet}
  </PageHeader>
  
  {#if tab === 'roles'}
    <RolesTab ctrl={roles} people={ctrl.people} />
  {:else}
  <section class="grid gap-4">
    <Panel class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
      <p class="font-sans text-sm text-muted-foreground">
        One sign-in for HiroLeague and its apps: a password given here, or Home Assistant's login while Home
        is connected. Roles says what each role may do here and in each app.
      </p>
      <Button disabled={ctrl.busy} onclick={() => ctrl.openAdd()}>
        <UserPlus size={15} /> Add person
      </Button>
    </Panel>
    <PeopleListCard {ctrl} />
  </section>
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
