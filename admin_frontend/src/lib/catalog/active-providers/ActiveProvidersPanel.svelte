<script lang="ts">
  import { Trash2 } from '@lucide/svelte';
  import AdminTableShell from '$lib/components/page/table/AdminTableShell.svelte';
  import { ADMIN_TABLE_GRID_ROW } from '$lib/components/page/table/admin-table-grid-row';
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import InlineEmptyState from '$lib/ui/InlineEmptyState.svelte';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';
  import type { ToastKind } from '$lib/ui/toast-types';
  import ActiveProvidersAddDialog from './active-providers-add-dialog.svelte';
  import ActiveProvidersRemoveDialog from './active-providers-remove-dialog.svelte';
  import type { ActiveProvidersStore } from './active-providers-store.svelte';

  type Notify = (kind: ToastKind, message: string) => void;

  type Props = {
    store: ActiveProvidersStore;
    notify: Notify;
  };

  let { store, notify }: Props = $props();

  const GRID_COLUMNS = '1.2fr 110px 130px 90px 1fr 120px';
</script>

<section class="grid gap-4 rounded-lg border bg-card p-5 shadow-sm">
  <div>
    <h3 class="text-lg font-semibold">Configured providers</h3>
    <span class="font-sans text-sm text-muted-foreground">
      {store.counts.total} configured / {store.counts.cloud} cloud / {store.counts.local} local
    </span>
  </div>

  {#if store.loading}
    <InlineLoading label="Loading active providers…" />
  {:else if store.error}
    <InlineDestructiveAlert title="Could not load active providers" message={store.error} />
  {:else if store.rows.length === 0}
    <InlineEmptyState
      message="No providers configured for this workspace."
      hint="Add an API key or scan your environment."
    />
  {:else}
    <AdminTableShell
      layout="grid"
      minWidth={900}
      gridColumns={GRID_COLUMNS}
      stickyHead
    >
      {#snippet headRow()}
        <span>Provider</span>
        <span>Hosting</span>
        <span>Auth</span>
        <span>Models</span>
        <span>Kinds</span>
        <span>Actions</span>
      {/snippet}
      {#snippet body()}
        {#each store.rows as provider (provider.provider_id)}
          <div class={ADMIN_TABLE_GRID_ROW} style:grid-template-columns={GRID_COLUMNS}>
            <span class="min-w-0">
              <strong class="block truncate font-sans text-sm">{provider.display_name}</strong>
              <small class="block truncate text-xs text-muted-foreground">{provider.provider_id}</small>
            </span>
            <span>
              <Badge variant={provider.hosting === 'cloud' ? 'secondary' : 'outline'}>
                {provider.hosting}
              </Badge>
            </span>
            <span class="truncate text-xs text-muted-foreground">{provider.auth_method}</span>
            <span class="text-right font-sans text-xs text-muted-foreground">
              {provider.available_model_count}
            </span>
            <span class="truncate text-xs text-muted-foreground">
              {store.providerKindLabel(provider)}
            </span>
            <span>
              <Button
                size="sm"
                variant="destructive"
                disabled={store.busy}
                onclick={() => store.openRemoveDialog(provider)}
              >
                <Trash2 size={13} /> Remove
              </Button>
            </span>
          </div>
        {/each}
      {/snippet}
    </AdminTableShell>
  {/if}
</section>

<ActiveProvidersAddDialog
  open={store.dialog === 'add'}
  loading={store.addableProvidersLoading}
  busy={store.busy}
  addableProviders={store.addableProviders}
  providerId={store.addForm.provider_id}
  apiKey={store.addForm.api_key}
  onClose={() => store.closeDialog()}
  onSubmit={() => void store.submitAddProvider(notify)}
  onProviderIdChange={(value) => {
    store.addForm = { ...store.addForm, provider_id: value };
  }}
  onApiKeyChange={(value) => {
    store.addForm = { ...store.addForm, api_key: value };
  }}
/>

<ActiveProvidersRemoveDialog
  open={store.dialog === 'remove'}
  busy={store.busy}
  provider={store.selectedProvider}
  onClose={() => store.closeDialog()}
  onSubmit={() => void store.submitRemoveProvider(notify)}
/>
