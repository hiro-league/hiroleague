<script lang="ts">
  import AdminTableHeaderCell from '$lib/components/page/table/AdminTableHeaderCell.svelte';
  import AdminTableShell from '$lib/components/page/table/AdminTableShell.svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import CatalogTabActions from '$lib/features/catalog/browse/CatalogTabActions.svelte';
  import type { CatalogController } from '$lib/features/catalog/state/catalog-controller.svelte';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import InlineEmptyState from '$lib/ui/InlineEmptyState.svelte';
  import ProviderFreeOffersBadge from '$lib/features/catalog/shared/ProviderFreeOffersBadge.svelte';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';
  import { AVAILABILITY_FILTER_UI } from '$lib/features/catalog/shared/catalog-filter-ui';
  import { ADMIN_SECTION_CARD, ADMIN_SECTION_HEADING_LG, ADMIN_TABLE_HEAD } from '$lib/styling/admin-tokens';
  import { cn } from '$lib/utils';

  type Props = {
    ctrl: CatalogController;
  };

  let { ctrl }: Props = $props();
</script>

<section class={ADMIN_SECTION_CARD}>
  <div class="mb-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
    <div>
      <h3 class={ADMIN_SECTION_HEADING_LG}>Catalog providers</h3>
      <span class="font-sans text-sm text-muted-foreground">
        {ctrl.providerCounts.total} providers / {ctrl.providerCounts.cloud} cloud / {ctrl.providerCounts.local} local
      </span>
    </div>
    <CatalogTabActions
      catalogReloadBusy={ctrl.catalogReloadBusy}
      refreshBusy={ctrl.providersLoading}
      onRefresh={() => ctrl.refreshCatalogProviders()}
    />
  </div>

  {#if ctrl.providersLoading && ctrl.providers.length === 0}
    <!-- See ModelsTab — keep existing rows mounted on refresh to avoid header flicker. -->
    <InlineLoading label="Loading catalog providers…" />
  {:else if ctrl.providersError}
    <InlineDestructiveAlert title="Could not load catalog providers" message={ctrl.providersError} />
  {:else if ctrl.providers.length === 0}
    <InlineEmptyState message="No providers in the bundled catalog." />
  {:else}
    <AdminTableShell stickyHead class={cn('min-w-[980px]', ctrl.providersLoading && 'opacity-60 transition-opacity')}>
      <thead class={ADMIN_TABLE_HEAD}>
        <tr>
          <AdminTableHeaderCell column="online" sort={ctrl.providerSort} class="w-12 text-center">
            Online
          </AdminTableHeaderCell>
          <AdminTableHeaderCell column="provider" sort={ctrl.providerSort}>Provider</AdminTableHeaderCell>
          <AdminTableHeaderCell column="hosting" sort={ctrl.providerSort}>Hosting</AdminTableHeaderCell>
          <th class="px-3 py-2 text-left">Credential env</th>
          <th class="px-3 py-2 text-left">Recommended models</th>
          <AdminTableHeaderCell column="updated" sort={ctrl.providerSort}>Updated</AdminTableHeaderCell>
        </tr>
      </thead>
      <tbody>
        {#each ctrl.sortedProviders as provider (provider.id)}
          {@const isOnline = ctrl.configuredWorkspaceProviderIds.has(provider.id)}
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
            </td>
            <td class="px-3 py-3">
              <Badge variant={provider.hosting === 'cloud' ? 'secondary' : 'outline'}>{provider.hosting}</Badge>
            </td>
            <td class="truncate px-3 py-3 text-xs text-muted-foreground">
              {provider.credential_env_keys?.length ? provider.credential_env_keys.join(', ') : '-'}
            </td>
            <td class="min-w-0 px-3 py-3">
              {#if provider.recommended_models}
                <ul class="space-y-2">
                  {#each Object.entries(provider.recommended_models) as [kind, modelId] (kind)}
                    <li>
                      <span class="block font-sans text-sm">
                        <span class="text-muted-foreground">{kind}:</span>
                        {ctrl.catalogModelDisplayNames[modelId] ?? modelId}
                      </span>
                      <small class="block truncate text-xs text-muted-foreground">{modelId}</small>
                    </li>
                  {/each}
                </ul>
              {:else}
                <span class="text-xs text-muted-foreground">-</span>
              {/if}
            </td>
            <td class="whitespace-nowrap px-3 py-3 text-xs text-muted-foreground">
              {provider.metadata_updated_at ?? '-'}
            </td>
          </tr>
        {/each}
      </tbody>
    </AdminTableShell>
  {/if}
</section>
