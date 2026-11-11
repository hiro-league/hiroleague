<script lang="ts">
  import ResourceView from '$kit/ui/resource-view.svelte';
  import Panel from '$kit/ui/panel.svelte';
  import { ArrowUpRight } from '@lucide/svelte';
  import { count } from '$kit/format/number';
  import AdminTableHeaderCell from '$lib/components/page/table/AdminTableHeaderCell.svelte';
  import TableShell from '$kit/ui/table-shell.svelte';
  import { Badge } from '$kit/components/ui/badge/index.js';
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
  import StatusDot from '$kit/ui/status-dot.svelte';
  import { ADMIN_TABLE_HEAD } from '$lib/styling/admin-tokens';
  import { cn } from '$lib/utils';

  type Props = {
    ctrl: CatalogController;
  };

  let { ctrl }: Props = $props();

  const view = $derived({
    data: ctrl.models.length === 0 && (ctrl.modelsLoading || ctrl.modelsError) ? null : ctrl.filteredModels,
    error: ctrl.modelsError ?? '',
    loading: ctrl.modelsLoading,
    reload: () => ctrl.loadModels()
  });
</script>

<Panel title="Models" description={`${ctrl.filteredModels.length} shown${ctrl.catalogVersion ? ` / catalog version ${ctrl.catalogVersion}` : ''}`}>
  {#snippet actions()}
    <CatalogTabActions
      catalogReloadBusy={ctrl.catalogReloadBusy}
      refreshBusy={ctrl.modelsLoading}
      onRefresh={() => ctrl.loadModels()}
    />
  {/snippet}
  <ResourceView
    resource={view}
    loadingLabel="Loading models…"
    errorTitle="Could not load models"
    empty={(d) => d.length === 0}
    emptyMessage="No models match the current filters."
    quiet
  >
    {#snippet children()}
      <!-- min-w is shared with ProvidersTab (keep in sync) so both tabs render at the same content
           width and switching Models↔Providers doesn't jump. -->
      <TableShell stickyHead class={cn('min-w-[1540px]', ctrl.modelsLoading && 'opacity-60 transition-opacity')}>
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
                  <StatusDot
                    tone="ok"
                    label={isLocal
                      ? 'Downloaded — available in this workspace'
                      : 'Online — provider configured in this workspace'}
                  />
                {:else}
                  <StatusDot
                    tone="off"
                    label={isLocal
                      ? `Not downloaded — ${model.manage_hint ?? 'manage in Settings'}`
                      : 'Offline — provider not configured in this workspace'}
                  />
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
                      class="shrink-0 text-brand"
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
                {typeof model.context_window === 'number' ? count(model.context_window) : '-'}
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
      </TableShell>
    {/snippet}
  </ResourceView>
</Panel>
