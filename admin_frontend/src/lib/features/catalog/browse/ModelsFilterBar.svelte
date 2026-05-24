<script lang="ts">
  import { FilterX } from '@lucide/svelte';
  import AdminFilterBar from '$lib/components/page/table/AdminFilterBar.svelte';
  import AdminFilterBarSelect from '$lib/components/page/table/AdminFilterBarSelect.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import type { CatalogController } from '$lib/features/catalog/state/catalog-controller.svelte';
  import {
    HOSTING_FILTER_IDS,
    HOSTING_FILTER_UI,
    MODEL_CLASS_OPTIONS,
    MODEL_KIND_FILTER_IDS,
    MODEL_KIND_FILTER_UI
  } from '$lib/features/catalog/shared/catalog-filter-ui';
  import { cn } from '$lib/utils';

  type Props = {
    ctrl: CatalogController;
  };

  let { ctrl }: Props = $props();

  const providerOptions = $derived(
    ctrl.providers.map((provider) => ({
      value: provider.id,
      label: `${provider.display_name} (${provider.id})`
    }))
  );

  const classOptions = $derived(
    MODEL_CLASS_OPTIONS.map((option) => ({
      value: option,
      label: option || 'All classes'
    }))
  );
</script>

<AdminFilterBar class="items-end">
  <AdminFilterBarSelect
    label="Provider"
    value={ctrl.modelFilters.filters.provider_id}
    placeholder="All providers"
    class="w-[220px]"
    options={providerOptions}
    onValueChange={(value) => {
      ctrl.modelFilters.set('provider_id', value);
      void ctrl.applyModelFilters();
    }}
  />
  <div class="grid min-w-[10rem] gap-1 font-sans text-xs font-semibold text-muted-foreground">
    <span id="catalog-kind-filters-label">Kind</span>
    <div
      class="flex h-9 items-center justify-center gap-0.5 rounded-md border bg-background px-1"
      role="group"
      aria-labelledby="catalog-kind-filters-label"
    >
      {#each MODEL_KIND_FILTER_IDS as kind (kind)}
        {@const { Icon, title } = MODEL_KIND_FILTER_UI[kind]}
        {@const on = ctrl.isModelKindSelected(kind)}
        <button
          type="button"
          class={cn(
            'flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-transparent transition-colors',
            on
              ? 'bg-primary text-primary-foreground shadow-sm'
              : 'text-muted-foreground opacity-55 hover:opacity-100',
            on && 'border-primary/20'
          )}
          title={title}
          aria-label={title}
          aria-pressed={on}
          onclick={() => void ctrl.toggleModelKindFilter(kind)}
        >
          <Icon size={16} strokeWidth={on ? 2.25 : 2} aria-hidden="true" />
        </button>
      {/each}
    </div>
  </div>
  <AdminFilterBarSelect
    label="Class"
    value={ctrl.modelFilters.filters.model_class}
    placeholder="All classes"
    class="w-[180px]"
    options={classOptions}
    onValueChange={(value) => {
      ctrl.modelFilters.set('model_class', value);
      void ctrl.applyModelFilters();
    }}
  />
  <div class="grid min-w-[10rem] gap-1 font-sans text-xs font-semibold text-muted-foreground">
    <span id="catalog-hosting-filters-label">Hosting</span>
    <div
      class="flex h-9 items-center justify-center gap-0.5 rounded-md border bg-background px-1"
      role="group"
      aria-labelledby="catalog-hosting-filters-label"
    >
      {#each HOSTING_FILTER_IDS as hosting (hosting)}
        {@const { Icon, title } = HOSTING_FILTER_UI[hosting]}
        {@const on = ctrl.isHostingSelected(hosting)}
        <button
          type="button"
          class={cn(
            'flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-transparent transition-colors',
            on
              ? 'bg-primary text-primary-foreground shadow-sm'
              : 'text-muted-foreground opacity-55 hover:opacity-100',
            on && 'border-primary/20'
          )}
          title={title}
          aria-label={title}
          aria-pressed={on}
          onclick={() => void ctrl.toggleHostingFilter(hosting)}
        >
          <Icon size={16} strokeWidth={on ? 2.25 : 2} aria-hidden="true" />
        </button>
      {/each}
    </div>
  </div>
  <div class="flex items-end">
    <Button
      variant="outline"
      disabled={!ctrl.hasModelFilters}
      onclick={() => void ctrl.clearModelFilters()}
    >
      <FilterX size={15} /> Clear filters
    </Button>
  </div>
</AdminFilterBar>
