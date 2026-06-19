<script lang="ts">
  import SingleModelPicker from '$lib/features/preferences/SingleModelPicker.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import {
    PREF_MODEL_EMPTY_LABELS,
    prefModelCatalog,
    type PrefModelIdPath,
    type PrefModelKind
  } from '$lib/features/preferences/shared/preferences-model-picker';

  type Props = {
    ctrl: PreferencesController;
    kind: PrefModelKind;
    path: PrefModelIdPath;
    label: string;
    hint?: string;
    selectedId?: string | null;
    busy?: boolean;
    embedded?: boolean;
    labelled?: boolean;
  };

  let {
    ctrl,
    kind,
    path,
    label,
    hint = '',
    selectedId = null,
    busy,
    embedded = false,
    labelled = false
  }: Props = $props();

  const catalog = $derived(prefModelCatalog(ctrl, kind));
  const empty = $derived(PREF_MODEL_EMPTY_LABELS[kind]);
  const pickerBusy = $derived(busy ?? ctrl.busy);
</script>

<SingleModelPicker
  {embedded}
  {labelled}
  {label}
  {hint}
  {selectedId}
  catalogModels={catalog.catalogModels}
  catalogAllProviders={ctrl.catalogAllProviders}
  workspaceActiveProvidersResolved={ctrl.activeProvidersStore.resolved}
  workspaceActiveProviderIds={catalog.workspaceActiveProviderIds}
  busy={pickerBusy}
  emptyProviders={empty.emptyProviders}
  emptyModelsForProvider={empty.emptyModelsForProvider}
  onSelect={(id) => ctrl.setModelId(path, id)}
/>
