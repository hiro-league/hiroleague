<script lang="ts">
  import AdminTableHeaderCell from '$lib/components/page/table/AdminTableHeaderCell.svelte';
  import AdminTableShell from '$lib/components/page/table/AdminTableShell.svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import CatalogTabActions from '$lib/features/catalog/browse/CatalogTabActions.svelte';
  import type { CatalogController } from '$lib/features/catalog/state/catalog-controller.svelte';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import InlineEmptyState from '$lib/ui/InlineEmptyState.svelte';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';
  import { ADMIN_SECTION_CARD, ADMIN_SECTION_HEADING_LG, ADMIN_TABLE_HEAD } from '$lib/styling/admin-tokens';

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
      onReload={() => ctrl.reloadBundledCatalog()}
      onRefresh={() => ctrl.refreshCatalogProviders()}
    />
  </div>

  {#if ctrl.providersLoading}
    <InlineLoading label="Loading catalog providers…" />
  {:else if ctrl.providersError}
    <InlineDestructiveAlert title="Could not load catalog providers" message={ctrl.providersError} />
  {:else if ctrl.providers.length === 0}
    <InlineEmptyState message="No providers in the bundled catalog." />
  {:else}
    <AdminTableShell class="min-w-[980px]">
      <thead class={ADMIN_TABLE_HEAD}>
        <tr>
          <AdminTableHeaderCell column="provider" sort={ctrl.providerSort}>Provider</AdminTableHeaderCell>
          <AdminTableHeaderCell column="hosting" sort={ctrl.providerSort}>Hosting</AdminTableHeaderCell>
          <th class="px-3 py-2 text-left">Credential env</th>
          <th class="px-3 py-2 text-left">Recommended models</th>
          <AdminTableHeaderCell column="updated" sort={ctrl.providerSort}>Updated</AdminTableHeaderCell>
        </tr>
      </thead>
      <tbody>
        {#each ctrl.sortedProviders as provider (provider.id)}
          <tr class="border-t">
            <td class="min-w-0 px-3 py-3">
              <button
                class="flex max-w-full items-center gap-2 text-left font-sans text-sm font-semibold text-primary hover:underline"
                type="button"
                onclick={() => void ctrl.openModelsForProvider(provider.id)}
                title={`View models for ${provider.display_name}`}
              >
                {#if ctrl.configuredWorkspaceProviderIds.has(provider.id)}
                  <span
                    class="size-2 shrink-0 rounded-full bg-green-600 dark:bg-green-500"
                    title="Configured for this workspace"
                    aria-hidden="true"
                  ></span>
                  <span class="sr-only">Configured for this workspace. </span>
                {/if}
                <span class="min-w-0 truncate">{provider.display_name}</span>
              </button>
              <small class="block truncate text-xs text-muted-foreground">{provider.id}</small>
            </td>
            <td class="px-3 py-3">
              <Badge variant={provider.hosting === 'cloud' ? 'secondary' : 'outline'}>{provider.hosting}</Badge>
            </td>
            <td class="truncate px-3 py-3 text-xs text-muted-foreground">
              {provider.credential_env_keys?.length ? provider.credential_env_keys.join(', ') : '-'}
            </td>
            <td class="min-w-0 px-3 py-3 text-xs text-muted-foreground">
              {#if provider.recommended_models}
                {Object.entries(provider.recommended_models)
                  .map(([kind, model]) => `${kind}: ${model}`)
                  .join(' / ')}
              {:else}
                -
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
