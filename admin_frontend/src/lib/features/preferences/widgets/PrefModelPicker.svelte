<script lang="ts">
  import SingleModelPicker from '$lib/features/preferences/SingleModelPicker.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import {
    PREF_MODEL_EMPTY_LABELS,
    prefModelCatalog,
    type PrefModelIdPath,
    type PrefModelKind
  } from '$lib/features/preferences/shared/preferences-model-picker';
  import { usePrefFieldVisibility } from '$lib/features/preferences/shared/preferences-advanced.svelte';
  import { getPreferenceByPath } from '$lib/features/preferences/state/preferences-edits';
  import {
    preferenceFieldMeta,
    preferenceHint,
    preferenceIsAdvanced,
    preferenceTitle
  } from '$lib/features/preferences/shared/preferences-schema';

  type Props = {
    ctrl: PreferencesController;
    kind: PrefModelKind;
    path: PrefModelIdPath;
    /** Optional label override; omit to use the field's backend `title` (single source of truth). */
    label?: string;
    /** Overrides the schema description; omit to use the field's backend `description`. */
    hint?: string;
    busy?: boolean;
    embedded?: boolean;
    labelled?: boolean;
    /** Inherited default model id shown in the empty box for override pickers (e.g. rerankers). */
    emptyFallbackId?: string | null;
  };

  let {
    ctrl,
    kind,
    path,
    label,
    hint: hintOverride,
    busy,
    embedded = false,
    labelled = false,
    emptyFallbackId = null
  }: Props = $props();

  const catalog = $derived(prefModelCatalog(ctrl, kind));
  const empty = $derived(PREF_MODEL_EMPTY_LABELS[kind]);
  const pickerBusy = $derived(busy ?? ctrl.busy);
  // Selected id is owned by `path` (read from the draft), not passed in — removes the double-write
  // where the call site repeated `selectedId={ctrl.draft.<path>}` alongside `path`.
  const selectedId = $derived(getPreferenceByPath(ctrl.draft, path) as string | null);
  const meta = $derived(preferenceFieldMeta(ctrl.fieldSchema, path));
  const resolvedLabel = $derived(label ?? preferenceTitle(meta) ?? path);
  const hint = $derived(hintOverride ?? preferenceHint(meta) ?? '');
  const vis = usePrefFieldVisibility(() => preferenceIsAdvanced(meta));
</script>

{#if vis.visible}
<div data-pref-path={path}>
<SingleModelPicker
  {embedded}
  {labelled}
  label={resolvedLabel}
  {path}
  {hint}
  {selectedId}
  catalogModels={catalog.catalogModels}
  catalogAllProviders={ctrl.catalogAllProviders}
  workspaceActiveProvidersResolved={ctrl.activeProvidersStore.resolved}
  workspaceActiveProviderIds={catalog.workspaceActiveProviderIds}
  busy={pickerBusy}
  emptyProviders={empty.emptyProviders}
  emptyModelsForProvider={empty.emptyModelsForProvider}
  {emptyFallbackId}
  onSelect={(id) => ctrl.setModelId(path, id)}
/>
</div>
{/if}
