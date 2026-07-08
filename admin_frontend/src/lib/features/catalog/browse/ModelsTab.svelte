<script lang="ts">
  import { ArrowUpRight } from '@lucide/svelte';
  import AdminTableHeaderCell from '$lib/components/page/table/AdminTableHeaderCell.svelte';
  import AdminTableShell from '$lib/components/page/table/AdminTableShell.svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import CatalogTabActions from '$lib/features/catalog/browse/CatalogTabActions.svelte';
  import type { CatalogController } from '$lib/features/catalog/state/catalog-controller.svelte';
  import {
    allCatalogKinds,
    catalogHostingUiForRow,
    catalogKindsTitle,
    isRowAvailable,
    listText,
    modelKindUiForRow
  } from '$lib/features/catalog/shared/catalog-filter-ui';
  import { modelPricing, pricingSourceHref } from '$lib/features/catalog/shared/catalog-pricing';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import InlineEmptyState from '$lib/ui/InlineEmptyState.svelte';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';
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
      <h3 class={ADMIN_SECTION_HEADING_LG}>Models</h3>
      <span class="font-sans text-sm text-muted-foreground">
        {ctrl.filteredModels.length} shown{ctrl.catalogVersion ? ` / catalog version ${ctrl.catalogVersion}` : ''}
      </span>
    </div>
    <CatalogTabActions
      catalogReloadBusy={ctrl.catalogReloadBusy}
      refreshBusy={ctrl.modelsLoading}
      onRefresh={() => ctrl.loadModels()}
    />
  </div>

  {#if ctrl.modelsLoading && ctrl.models.length === 0}
    <!-- Only show the full placeholder on the initial load (no rows yet).
         Filter-driven reloads keep the existing table mounted so the document
         height stays stable, which prevents the sticky page header from
         flickering back to expanded mode while fetching. -->
    <InlineLoading label="Loading models…" />
  {:else if ctrl.modelsError}
    <InlineDestructiveAlert title="Could not load models" message={ctrl.modelsError} />
  {:else if ctrl.filteredModels.length === 0}
    <InlineEmptyState message="No models match the current filters." />
  {:else}
    <!-- min-w is shared with ProvidersTab (keep in sync) so both tabs render at the same content
         width and switching Models↔Providers doesn't jump. -->
    <AdminTableShell stickyHead class={cn('min-w-[1540px]', ctrl.modelsLoading && 'opacity-60 transition-opacity')}>
      <thead class={ADMIN_TABLE_HEAD}>
        <tr>
          <AdminTableHeaderCell column="online" sort={ctrl.modelSort} class="w-12 text-center">
            Online
          </AdminTableHeaderCell>
          <AdminTableHeaderCell column="provider" sort={ctrl.modelSort}>Provider</AdminTableHeaderCell>
          <AdminTableHeaderCell column="model" sort={ctrl.modelSort}>Model</AdminTableHeaderCell>
          <AdminTableHeaderCell column="kind" sort={ctrl.modelSort}>Kind</AdminTableHeaderCell>
          <AdminTableHeaderCell column="class" sort={ctrl.modelSort}>Class</AdminTableHeaderCell>
          <AdminTableHeaderCell column="hosting" sort={ctrl.modelSort}>Hosting</AdminTableHeaderCell>
          <AdminTableHeaderCell column="context" sort={ctrl.modelSort} class="text-center">
            Context
          </AdminTableHeaderCell>
          <th class="px-3 py-2 text-left">Pricing</th>
          <th class="px-3 py-2 text-left">Features</th>
        </tr>
      </thead>
      <tbody>
        {#each ctrl.sortedModels as model (model.id)}
          {@const kindKeys = allCatalogKinds(model)}
          {@const hostingUi = catalogHostingUiForRow(model.hosting)}
          {@const HostingIcon = hostingUi.Icon}
          {@const priceHref = pricingSourceHref(model)}
          {@const isLocal = model.source === 'local'}
          {@const available = isRowAvailable(model, ctrl.configuredWorkspaceProviderIds)}
          <tr class="border-t">
            <td class="px-2 py-3 text-center">
              {#if available}
                <span
                  class="inline-block size-2 rounded-full bg-green-600 dark:bg-green-500"
                  title={isLocal
                    ? 'Downloaded — available in this workspace'
                    : 'Online — provider configured in this workspace'}
                  aria-hidden="true"
                ></span>
                <span class="sr-only">{isLocal ? 'Downloaded. ' : 'Online. '}</span>
              {:else}
                <span
                  class="inline-block size-2 rounded-full bg-muted-foreground/40"
                  title={isLocal
                    ? `Not downloaded — ${model.manage_hint ?? 'manage in Settings'}`
                    : 'Offline — provider not configured in this workspace'}
                  aria-hidden="true"
                ></span>
                <span class="sr-only">{isLocal ? 'Not downloaded. ' : 'Offline. '}</span>
              {/if}
            </td>
            <td class="px-3 py-3">
              <span class="block min-w-0 truncate text-sm">
                {ctrl.providerLabels[model.provider_id] ?? model.provider_id}
              </span>
            </td>
            <td class="min-w-0 px-3 py-3">
              <strong class="flex min-w-0 items-baseline gap-1 font-sans text-sm">
                {#if ctrl.recommendedCatalogModelIds.has(model.id)}
                  <span
                    class="shrink-0 text-amber-500 dark:text-amber-400"
                    title="Recommended default in catalog for this provider and kind"
                    aria-hidden="true"
                  >★</span>
                  <span class="sr-only">Recommended. </span>
                {/if}
                <span class="min-w-0 truncate">{model.display_name}</span>
                {#if isLocal}
                  <Badge variant="outline" class="shrink-0 text-[10px]">Local</Badge>
                {/if}
              </strong>
              <small class="block truncate text-xs text-muted-foreground">
                {model.id}{#if isLocal && model.size_label} · {model.size_label}{/if}
              </small>
            </td>
            <td class="px-3 py-3">
              <span class="flex flex-wrap justify-center gap-0.5" title={catalogKindsTitle(model)}>
                {#each kindKeys as k (k)}
                  {@const kui = modelKindUiForRow(k)}
                  {@const SubIcon = kui.Icon}
                  <span
                    class="inline-flex h-8 w-8 items-center justify-center rounded-md border bg-muted/40 text-foreground"
                    title={kui.title}
                  >
                    <SubIcon size={16} strokeWidth={2} aria-hidden="true" />
                    <span class="sr-only">{kui.title}</span>
                  </span>
                {/each}
              </span>
            </td>
            <td class="truncate px-3 py-3 text-sm text-muted-foreground">{model.model_class ?? '-'}</td>
            <td class="px-3 py-3">
              <span class="flex justify-center">
                <span
                  class="inline-flex h-8 w-8 items-center justify-center rounded-md border bg-muted/40 text-foreground"
                  title={hostingUi.title}
                >
                  <HostingIcon size={16} strokeWidth={2} aria-hidden="true" />
                  <span class="sr-only">{hostingUi.title}</span>
                </span>
              </span>
            </td>
            <td class="px-3 py-3 text-center font-sans text-xs text-muted-foreground">
              {typeof model.context_window === 'number' ? model.context_window.toLocaleString() : '-'}
            </td>
            <td class="px-3 py-3">
              <span class="flex min-w-0 flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                <span class="min-w-0 whitespace-pre-line">{modelPricing(model)}</span>
                {#if priceHref}
                  <a
                    href={priceHref}
                    target="_blank"
                    rel="noopener noreferrer"
                    class="inline-flex shrink-0 text-primary hover:text-primary/90"
                    title="Open vendor pricing source"
                    aria-label="Open vendor pricing source in new tab"
                  >
                    <ArrowUpRight size={15} strokeWidth={2.25} aria-hidden="true" />
                  </a>
                {/if}
              </span>
            </td>
            <td
              class="min-w-0 px-3 py-3 text-sm leading-snug break-words text-muted-foreground"
              title={listText(model.features)}
            >
              {listText(model.features)}
            </td>
          </tr>
        {/each}
      </tbody>
    </AdminTableShell>
  {/if}
</section>
