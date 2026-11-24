<script lang="ts">
  import { KeyRound, MessageCircle, MonitorSmartphone, Pencil, Trash2, RefreshCw } from '@lucide/svelte';
  import type { DeviceRow } from '$lib/api/devices';
  import { Badge } from '$kit/components/ui/badge/index.js';
  import { Button } from '$kit/components/ui/button/index.js';
  import ResourceView from '$kit/ui/resource-view.svelte';
  import Panel from '$kit/ui/panel.svelte';
  import TableShell from '$kit/ui/table-shell.svelte';
  import { TABLE_GRID_ROW } from '$kit/ui/table-grid';
  import { shownNumber, type PeopleController } from '../state/people-controller.svelte';

  // Permissions phase 3: a person's devices beside their WhatsApp address (`devicesOf`)
  let { ctrl, devicesOf }: { ctrl: PeopleController; devicesOf: (personId: string) => DeviceRow[] } = $props();

  const GRID = '1.1fr 1fr 170px 1.4fr 150px 210px';
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
          <span>Roles</span>
          <span>Talks to Hiro on</span>
          <span>Admin sign-in</span>
          <span class="text-right">Actions</span>
        {/snippet}
        {#snippet body()}
          {#each ctrl.people as person (person.person_id)}
            {@const devices = devicesOf(person.person_id)}
            <div class={TABLE_GRID_ROW} style:grid-template-columns={GRID}>
              <span class="truncate font-sans text-sm font-semibold">{person.name}</span>
              <span class="truncate font-sans text-sm">{person.calls_them || person.name}</span>
              <span class="flex flex-wrap gap-1">
                {#each ctrl.rolesOf(person) as roleId (roleId)}
                  <Badge variant={roleId === 'owner' ? 'default' : 'secondary'}>{ctrl.roleName(roleId)}</Badge>
                {/each}
              </span>
              <!-- Where a person talks to Hiro: their address on each chat channel, and their devices -->
              <span class="flex min-w-0 flex-wrap content-start items-center gap-1">
                {#if person.whatsapp}
                  <Badge variant="outline" class="gap-1 font-mono" title="WhatsApp">
                    <MessageCircle size={12} />{shownNumber(person.whatsapp)}
                  </Badge>
                {/if}
                {#each devices as device (device.device_id)}
                  <Badge variant="secondary" class="gap-1" title="A paired device">
                    <MonitorSmartphone size={12} />{device.device_name ?? device.device_id}
                  </Badge>
                {/each}
                {#if !person.whatsapp && devices.length === 0}
                  <span class="text-xs text-muted-foreground">none</span>
                {/if}
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
