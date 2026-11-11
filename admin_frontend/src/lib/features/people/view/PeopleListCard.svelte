<script lang="ts">
  import { KeyRound, Pencil, Trash2, RefreshCw } from '@lucide/svelte';
  import { Badge } from '$kit/components/ui/badge/index.js';
  import { Button } from '$kit/components/ui/button/index.js';
  import ResourceView from '$kit/ui/resource-view.svelte';
  import Panel from '$kit/ui/panel.svelte';
  import TableShell from '$kit/ui/table-shell.svelte';
  import { ADMIN_TABLE_GRID_ROW } from '$lib/components/page/table/admin-table-grid-row';
  import { shownNumber, type PeopleController } from '../state/people-controller.svelte';

  let { ctrl }: { ctrl: PeopleController } = $props();

  const GRID = '1.2fr 1fr 110px 170px 150px 210px';
  // ResourceView's shape: nothing to show yet reads as loading / failed; rows already held stay up while it reloads.
  const view = $derived({
    data: ctrl.people.length || !(ctrl.loading || ctrl.error) ? ctrl.people : null,
    error: ctrl.error ?? '',
    loading: ctrl.loading,
    reload: () => ctrl.load()
  });
</script>

<Panel title="Family" description={`${ctrl.people.length} ${ctrl.people.length === 1 ? 'person' : 'people'}`} class="grid gap-4">
  {#snippet actions()}
    <Button variant="outline" disabled={ctrl.loading} onclick={() => void ctrl.load()}>
      <RefreshCw size={15} /> Refresh
    </Button>
  {/snippet}
  <ResourceView
    resource={view}
    loadingLabel="Loading the family list…"
    errorTitle="Could not load the family list"
    empty={(d) => d.length === 0}
    emptyMessage="Nobody in the family list yet."
    quiet
  >
    {#snippet children()}
      <TableShell layout="grid" minWidth={900} gridColumns={GRID} stickyHead>
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
      </TableShell>
    {/snippet}
  </ResourceView>
</Panel>
