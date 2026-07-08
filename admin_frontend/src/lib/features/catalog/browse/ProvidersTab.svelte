<script lang="ts">
  import { Filter, Plus, RefreshCw, Search, Trash2 } from '@lucide/svelte';
  import AdminTableHeaderCell from '$lib/components/page/table/AdminTableHeaderCell.svelte';
  import AdminTableShell from '$lib/components/page/table/AdminTableShell.svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import CatalogTabActions from '$lib/features/catalog/browse/CatalogTabActions.svelte';
  import type { CatalogController } from '$lib/features/catalog/state/catalog-controller.svelte';
  import ActiveProvidersAddDialog from '$lib/catalog/active-providers/active-providers-add-dialog.svelte';
  import ActiveProvidersRemoveDialog from '$lib/catalog/active-providers/active-providers-remove-dialog.svelte';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import InlineEmptyState from '$lib/ui/InlineEmptyState.svelte';
  import ProviderFreeOffersBadge from '$lib/features/catalog/shared/ProviderFreeOffersBadge.svelte';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';
  import { AVAILABILITY_FILTER_UI, formatProviderKindsLabel } from '$lib/features/catalog/shared/catalog-filter-ui';
  import { ADMIN_SECTION_CARD, ADMIN_SECTION_HEADING_LG, ADMIN_TABLE_HEAD } from '$lib/styling/admin-tokens';
  import { cn } from '$lib/utils';

  type Props = {
    ctrl: CatalogController;
  };

  let { ctrl }: Props = $props();

  // Configured-provider store: this tab merges the bundled catalog with the workspace's configured
  // providers, so each catalog row can show its credential/auth state and offer add/remove inline.
  const store = $derived(ctrl.activeProvidersStore);

  // "Active only" toggle reproduces the former Active-providers view — online (configured) rows only.
  let activeOnly = $state(false);
  const visibleProviders = $derived(
    activeOnly
      ? ctrl.sortedProviders.filter((p) => ctrl.configuredWorkspaceProviderIds.has(p.id))
      : ctrl.sortedProviders
  );
  // Count line follows what's shown so it stays consistent when the toggle is on.
  const counts = $derived(
    visibleProviders.reduce(
      (acc, p) => {
        acc.total += 1;
        if (p.hosting === 'cloud') acc.cloud += 1;
        if (p.hosting === 'local') acc.local += 1;
        return acc;
      },
      { total: 0, cloud: 0, local: 0 }
    )
  );

  // Per-row expand state for the Recommended models column (collapsed shows the first entry only).
  let expandedRecommended = $state<Record<string, boolean>>({});
</script>

<section class={ADMIN_SECTION_CARD}>
  <div class="mb-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
    <div>
      <h3 class={ADMIN_SECTION_HEADING_LG}>Providers</h3>
      <span class="font-sans text-sm text-muted-foreground">
        {counts.total} {activeOnly ? 'active' : 'providers'} / {counts.cloud} cloud / {counts.local} local
      </span>
    </div>
    <div class="flex flex-wrap items-center justify-end gap-2">
      <Button
        variant={activeOnly ? 'default' : 'outline'}
        size="icon"
        aria-pressed={activeOnly}
        onclick={() => (activeOnly = !activeOnly)}
        title={activeOnly ? 'Showing active only — click to show all providers' : 'Show active (online) providers only'}
      >
        <Filter size={15} />
        <span class="sr-only">{activeOnly ? 'Show all providers' : 'Show active only'}</span>
      </Button>
      <Button
        variant="outline"
        disabled={store.busy}
        onclick={() => void store.scanEnvironment()}
        title="Import provider API keys found in the server environment"
      >
        <Search size={15} /> Scan environment
      </Button>
      <Button disabled={store.busy} onclick={() => void store.openAddDialog()}>
        <Plus size={15} /> Add provider
      </Button>
      <CatalogTabActions
        catalogReloadBusy={ctrl.catalogReloadBusy}
        refreshBusy={ctrl.providersLoading}
        onRefresh={() => ctrl.refreshCatalogProviders()}
        onReloadCatalog={() => void ctrl.reloadBundledCatalog()}
      />
    </div>
  </div>

  {#if ctrl.providersLoading && ctrl.providers.length === 0}
    <!-- See ModelsTab — keep existing rows mounted on refresh to avoid header flicker. -->
    <InlineLoading label="Loading providers…" />
  {:else if ctrl.providersError}
    <InlineDestructiveAlert title="Could not load providers" message={ctrl.providersError} />
  {:else if visibleProviders.length === 0}
    <InlineEmptyState
      message={activeOnly ? 'No active (online) providers.' : 'No providers in the bundled catalog.'}
      hint={activeOnly ? 'Add a provider or turn off the active-only filter.' : undefined}
    />
  {:else}
    <!-- min-w is shared with ModelsTab (keep in sync) so both tabs render at the same content width
         and switching Providers↔Models doesn't jump. Sized just above the wider table's natural width. -->
    <AdminTableShell stickyHead class={cn('min-w-[1540px]', ctrl.providersLoading && 'opacity-60 transition-opacity')}>
      <thead class={ADMIN_TABLE_HEAD}>
        <tr>
          <AdminTableHeaderCell column="online" sort={ctrl.providerSort} class="w-12 text-center">
            Online
          </AdminTableHeaderCell>
          <AdminTableHeaderCell column="provider" sort={ctrl.providerSort}>Provider</AdminTableHeaderCell>
          <AdminTableHeaderCell column="hosting" sort={ctrl.providerSort}>Hosting</AdminTableHeaderCell>
          <th class="px-3 py-2 text-left">Auth</th>
          <th class="px-3 py-2 text-center">Models</th>
          <th class="px-3 py-2 text-left">Kinds</th>
          <th class="px-3 py-2 text-left">Credential env</th>
          <th class="px-3 py-2 text-left">Recommended models</th>
          <AdminTableHeaderCell column="updated" sort={ctrl.providerSort}>Updated</AdminTableHeaderCell>
          <th class="px-3 py-2 text-left">Actions</th>
        </tr>
      </thead>
      <tbody>
        {#each visibleProviders as provider (provider.id)}
          {@const active = store.rowsByProviderId.get(provider.id)}
          {@const isOnline = ctrl.configuredWorkspaceProviderIds.has(provider.id)}
          {@const stats = ctrl.catalogModelStatsByProvider[provider.id]}
          <tr class="border-t">
            <td class="px-2 py-3 text-center">
              {#if isOnline}
                <span
                  class="inline-block size-2 rounded-full {AVAILABILITY_FILTER_UI.online.circleClass}"
                  title={AVAILABILITY_FILTER_UI.online.title}
                  aria-hidden="true"
                ></span>
                <span class="sr-only">Online. </span>
              {:else}
                <span
                  class="inline-block size-2 rounded-full {AVAILABILITY_FILTER_UI.offline.circleClass}"
                  title={AVAILABILITY_FILTER_UI.offline.title}
                  aria-hidden="true"
                ></span>
                <span class="sr-only">Offline. </span>
              {/if}
            </td>
            <td class="min-w-0 px-3 py-3">
              <div class="inline-flex max-w-full items-center gap-1">
                <button
                  class="min-w-0 truncate text-left font-sans text-sm font-semibold text-primary hover:underline"
                  type="button"
                  onclick={() => void ctrl.openModelsForProvider(provider.id)}
                  title={`View models for ${provider.display_name}`}
                >
                  {provider.display_name}
                </button>
                <ProviderFreeOffersBadge
                  providerDisplayName={provider.display_name}
                  offers={provider.free_offers ?? []}
                />
              </div>
              <small class="block truncate text-xs text-muted-foreground">{provider.id}</small>
              {#if active?.auth_method === 'local_endpoint'}
                {@const st = store.localStatus[provider.id]}
                <small class="block text-xs">
                  {#if st?.checking}
                    <span class="text-muted-foreground">Checking…</span>
                  {:else if st?.result?.online}
                    {@const pulled = st.result.catalog_status.filter((m) => m.pulled).length}
                    <span class="text-green-700 dark:text-green-500">● online</span>
                    <span class="text-muted-foreground">
                      · {pulled}/{st.result.catalog_status.length} models pulled
                    </span>
                  {:else if st?.result}
                    <span class="text-amber-600 dark:text-amber-500" title={st.result.error ?? ''}>
                      ● offline
                    </span>
                  {:else}
                    <span class="text-muted-foreground">● status unknown</span>
                  {/if}
                </small>
              {/if}
            </td>
            <td class="px-3 py-3">
              <Badge variant={provider.hosting === 'cloud' ? 'secondary' : 'outline'}>{provider.hosting}</Badge>
            </td>
            <td class="truncate px-3 py-3 text-xs text-muted-foreground">{active?.auth_method ?? '-'}</td>
            <!-- Models count & Kinds come from the provider's catalog (intrinsic to the provider),
                 not the active-providers join, so they show for every row. Fall back to the active
                 row for providers that aren't in the bundled catalog model list (e.g. built-in local). -->
            <td class="px-3 py-3 text-center text-xs text-muted-foreground">
              {stats ? stats.count : (active ? active.available_model_count : '-')}
            </td>
            <td class="truncate px-3 py-3 text-xs text-muted-foreground">
              {stats ? formatProviderKindsLabel(stats.kinds) : (active ? store.providerKindLabel(active) : '-')}
            </td>
            <td class="truncate px-3 py-3 text-xs text-muted-foreground">
              {provider.credential_env_keys?.length ? provider.credential_env_keys.join(', ') : '-'}
            </td>
            <td class="min-w-0 px-3 py-3">
              {#if provider.recommended_models && Object.keys(provider.recommended_models).length}
                {@const entries = Object.entries(provider.recommended_models)}
                {@const expanded = expandedRecommended[provider.id] ?? false}
                <ul class="space-y-2">
                  {#each expanded ? entries : entries.slice(0, 1) as [kind, modelId] (kind)}
                    <li>
                      <span class="block font-sans text-sm">
                        <span class="text-muted-foreground">{kind}:</span>
                        {ctrl.catalogModelDisplayNames[modelId] ?? modelId}
                      </span>
                      <small class="block truncate text-xs text-muted-foreground">{modelId}</small>
                    </li>
                  {/each}
                </ul>
                {#if entries.length > 1}
                  <button
                    type="button"
                    class="mt-1 text-xs font-medium text-primary hover:underline"
                    onclick={() =>
                      (expandedRecommended = { ...expandedRecommended, [provider.id]: !expanded })}
                  >
                    {expanded ? 'Show less' : `+${entries.length - 1} more`}
                  </button>
                {/if}
              {:else}
                <span class="text-xs text-muted-foreground">-</span>
              {/if}
            </td>
            <td class="whitespace-nowrap px-3 py-3 text-xs text-muted-foreground">
              {provider.metadata_updated_at ?? '-'}
            </td>
            <td class="px-3 py-3">
              {#if active?.auth_method === 'local'}
                <span class="text-xs text-muted-foreground" title="Built-in local models — no key to remove">
                  Built-in
                </span>
              {:else if active}
                <div class="flex items-center gap-1">
                  {#if active.auth_method === 'local_endpoint'}
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={store.busy || store.localStatus[provider.id]?.checking}
                      onclick={() => void store.probeProvider(provider.id)}
                      title="Re-check endpoint reachability"
                    >
                      <RefreshCw size={13} /> Recheck
                    </Button>
                  {/if}
                  <Button
                    size="sm"
                    variant="destructive"
                    disabled={store.busy}
                    onclick={() => store.openRemoveDialog(active)}
                  >
                    <Trash2 size={13} /> Remove
                  </Button>
                </div>
              {:else}
                <Button
                  size="sm"
                  variant="outline"
                  disabled={store.busy}
                  onclick={() => void store.openAddDialog(provider.id)}
                >
                  <Plus size={13} /> Add
                </Button>
              {/if}
            </td>
          </tr>
        {/each}
      </tbody>
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
  accountId={store.addForm.account_id}
  baseUrl={store.addForm.base_url}
  checking={store.checking}
  checkResult={store.checkResult}
  onClose={() => store.closeDialog()}
  onSubmit={() => void store.submitAddProvider()}
  onTest={() => void store.testConnection()}
  onProviderIdChange={(value) => {
    // Switching provider re-prefills the suggested endpoint for local providers (blank for cloud).
    const next = store.addableProviders.find((p) => p.id === value);
    store.addForm = { ...store.addForm, provider_id: value, base_url: next?.default_base_url ?? '' };
    store.clearCheckResult();
  }}
  onApiKeyChange={(value) => {
    store.addForm = { ...store.addForm, api_key: value };
  }}
  onAccountIdChange={(value) => {
    store.addForm = { ...store.addForm, account_id: value };
  }}
  onBaseUrlChange={(value) => {
    store.addForm = { ...store.addForm, base_url: value };
    store.clearCheckResult();
  }}
/>

<ActiveProvidersRemoveDialog
  open={store.dialog === 'remove'}
  busy={store.busy}
  provider={store.selectedProvider}
  onClose={() => store.closeDialog()}
  onSubmit={() => void store.submitRemoveProvider()}
/>
