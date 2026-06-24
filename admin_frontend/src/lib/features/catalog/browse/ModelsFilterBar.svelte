<script lang="ts">
  import { FilterX } from '@lucide/svelte';
  import AdminFilterBar from '$lib/components/page/table/AdminFilterBar.svelte';
  import AdminFilterBarSelect from '$lib/components/page/table/AdminFilterBarSelect.svelte';
  import AdminIconToggleGroup from '$lib/components/page/AdminIconToggleGroup.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import type { CatalogController } from '$lib/features/catalog/state/catalog-controller.svelte';
  import {
    AVAILABILITY_FILTER_IDS,
    AVAILABILITY_FILTER_UI,
    HOSTING_FILTER_IDS,
    HOSTING_FILTER_UI,
    MODEL_CLASS_OPTIONS,
    MODEL_KIND_FILTER_IDS,
    MODEL_KIND_FILTER_UI
  } from '$lib/features/catalog/shared/catalog-filter-ui';

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

  const kindOptions = $derived(
    MODEL_KIND_FILTER_IDS.map((kind) => ({
      value: kind,
      label: MODEL_KIND_FILTER_UI[kind].title,
      Icon: MODEL_KIND_FILTER_UI[kind].Icon
    }))
  );

  const hostingOptions = $derived(
    HOSTING_FILTER_IDS.map((hosting) => ({
      value: hosting,
      label: HOSTING_FILTER_UI[hosting].title,
      Icon: HOSTING_FILTER_UI[hosting].Icon
    }))
  );

  const availabilityOptions = $derived(
    AVAILABILITY_FILTER_IDS.map((availability) => ({
      value: availability,
      label: AVAILABILITY_FILTER_UI[availability].title,
      dotClass: AVAILABILITY_FILTER_UI[availability].circleClass
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
  <AdminIconToggleGroup
    label="Kind"
    labelId="catalog-kind-filters-label"
    options={kindOptions}
    isSelected={(kind) => ctrl.isModelKindSelected(kind as (typeof MODEL_KIND_FILTER_IDS)[number])}
    onToggle={(kind) => void ctrl.toggleModelKindFilter(kind as (typeof MODEL_KIND_FILTER_IDS)[number])}
    groupClass="min-w-[10rem]"
  />
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
  <AdminIconToggleGroup
    label="Hosting"
    labelId="catalog-hosting-filters-label"
    options={hostingOptions}
    isSelected={(hosting) => ctrl.isHostingSelected(hosting as (typeof HOSTING_FILTER_IDS)[number])}
    onToggle={(hosting) => void ctrl.toggleHostingFilter(hosting as (typeof HOSTING_FILTER_IDS)[number])}
    groupClass="min-w-[10rem]"
  />
  <AdminIconToggleGroup
    label="Online"
    labelId="catalog-availability-filters-label"
    activeStyle="muted"
    options={availabilityOptions}
    isSelected={(availability) =>
      ctrl.isAvailabilitySelected(availability as (typeof AVAILABILITY_FILTER_IDS)[number])}
    onToggle={(availability) =>
      ctrl.toggleAvailabilityFilter(availability as (typeof AVAILABILITY_FILTER_IDS)[number])}
    groupClass="min-w-[6.5rem]"
    containerClass="gap-1 px-1.5"
  />
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
