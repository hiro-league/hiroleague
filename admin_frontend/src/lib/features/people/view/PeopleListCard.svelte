<script lang="ts">
  import { KeyRound, Pencil, Trash2 } from '@lucide/svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import AdminTableShell from '$lib/components/page/table/AdminTableShell.svelte';
  import { ADMIN_TABLE_GRID_ROW } from '$lib/components/page/table/admin-table-grid-row';
  import RefreshableSectionCard from '$lib/features/channels-devices/shared/RefreshableSectionCard.svelte';
  import { shownNumber, type PeopleController } from '../state/people-controller.svelte';

  let { ctrl }: { ctrl: PeopleController } = $props();

  const GRID = '1.2fr 1fr 110px 170px 150px 210px';
</script>

<RefreshableSectionCard
  title="Family"
  countText="{ctrl.people.length} {ctrl.people.length === 1 ? 'person' : 'people'}"
  loading={ctrl.loading}
  error={ctrl.error}
  empty={ctrl.people.length === 0}
  loadingLabel="Loading the family list…"
  errorTitle="Could not load the family list"
  emptyMessage="Nobody in the family list yet."
  onRefresh={() => void ctrl.load()}
>
  <AdminTableShell layout="grid" minWidth={900} gridColumns={GRID} stickyHead>
    {#snippet headRow()}
      <span>Name</span>
      <span>Hiro calls them</span>
      <span>Role</span>
      <span>WhatsApp</span>
      <span>Admin sign-in</span>
      <span class="text-right">Actions</span>
    {/snippet}
    {#snippet body()}
      {#each ctrl.people as person (person.person_id)}
        <div class={ADMIN_TABLE_GRID_ROW} style:grid-template-columns={GRID}>
          <span class="truncate font-sans text-sm font-semibold">{person.name}</span>
          <span class="truncate font-sans text-sm">{person.calls_them || person.name}</span>
          <span><Badge variant={person.role_id === 'owner' ? 'default' : 'secondary'}>{ctrl.roleName(person.role_id)}</Badge></span>
          <span class="truncate font-mono text-xs" class:text-muted-foreground={!person.whatsapp}>
            {shownNumber(person.whatsapp) || 'none'}
          </span>
          <span class="truncate font-sans text-sm" class:text-muted-foreground={!person.has_sign_in}>
            {person.sign_in ?? 'no'}
          </span>
          <span class="flex justify-end gap-1.5">
            <Button size="sm" variant="outline" disabled={ctrl.busy} onclick={() => ctrl.openEdit(person)} title="Edit">
              <Pencil size={13} />
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={ctrl.busy}
              onclick={() => ctrl.openSignIn(person)}
              title={person.has_sign_in ? 'Change the sign-in name or password' : 'Let them sign in to the admin'}
            >
              <KeyRound size={13} /> {person.has_sign_in ? 'Sign-in' : 'Give sign-in'}
            </Button>
            <Button
              size="sm"
              variant="destructive"
              disabled={ctrl.busy}
              onclick={() => (ctrl.removeTarget = person)}
              title="Remove from the family list"
            >
              <Trash2 size={13} />
            </Button>
          </span>
        </div>
      {/each}
    {/snippet}
  </AdminTableShell>
</RefreshableSectionCard>
