<script lang="ts">
  /**
   * Renders one `PrefFieldSpec` from the manifest into the matching widget. Recursive: grid / column /
   * panel / gated layout specs render their children through this same component. `custom` specs are
   * resolved against the field-component registry below (string key → component), so the manifest data
   * module never imports `.svelte` files.
   */
  import type { Component } from 'svelte';
  import { cn } from '$lib/utils';
  import type { WorkspacePreferences } from '$lib/api/preferences';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { getPreferenceByPath } from '$lib/features/preferences/state/preferences-edits';
  import {
    preferenceFieldMeta,
    preferenceHint
  } from '$lib/features/preferences/shared/preferences-schema';
  import type { CustomFieldKey, PrefFieldSpec } from './manifest-types';
  import Badge from '$lib/components/ui/badge.svelte';
  import PrefFieldGrid from '$lib/features/preferences/widgets/PrefFieldGrid.svelte';
  import PrefNumberField from '$lib/features/preferences/widgets/PrefNumberField.svelte';
  import PrefTextField from '$lib/features/preferences/widgets/PrefTextField.svelte';
  import PrefToggleField from '$lib/features/preferences/widgets/PrefToggleField.svelte';
  import PrefTextareaField from '$lib/features/preferences/widgets/PrefTextareaField.svelte';
  import PrefSelectField from '$lib/features/preferences/widgets/PrefSelectField.svelte';
  import PrefModelPicker from '$lib/features/preferences/widgets/PrefModelPicker.svelte';
  import ModelWithProfilePair from '$lib/features/preferences/widgets/ModelWithProfilePair.svelte';
  import TuningProfileSelect from '$lib/features/preferences/widgets/TuningProfileSelect.svelte';
  import PrefModelDownload from '$lib/features/preferences/widgets/PrefModelDownload.svelte';
  import PrefPanel from '$lib/features/preferences/widgets/PrefPanel.svelte';
  import PromptField from '$lib/features/preferences/widgets/prompts/PromptField.svelte';
  import ActivePromptLibraryField from '$lib/features/preferences/widgets/prompts/ActivePromptLibraryField.svelte';
  import FieldHelp from '$lib/components/ui/field-help.svelte';
  import PrefFieldRenderer from './PrefFieldRenderer.svelte';
  import GraphEvalContextToggles from '$lib/features/preferences/sections/graph-engine/GraphEvalContextToggles.svelte';

  let { ctrl, spec }: { ctrl: PreferencesController; spec: PrefFieldSpec } = $props();

  // String key → bespoke field component. The typed record makes a missing/typo key a compile error.
  const CUSTOM_FIELDS: Record<CustomFieldKey, Component<{ ctrl: PreferencesController }>> = {
    graphEvalContextToggles: GraphEvalContextToggles
  };

  const HEADING_CLASS =
    'inline-flex items-center gap-1.5 font-sans text-base font-semibold leading-snug text-foreground';

  // The manifest renders under a `{#if ctrl.draft}` guard, so draft is present for predicates/options.
  const draft = $derived(ctrl.draft as WorkspacePreferences);
</script>

{#if spec.kind === 'number'}
  <PrefNumberField {ctrl} path={spec.path} disabled={spec.disabledWhen?.(draft) ?? false} />
{:else if spec.kind === 'text'}
  <PrefTextField
    {ctrl}
    path={spec.path}
    placeholder={spec.placeholder}
    maxlength={spec.maxlength}
    hint={spec.hint}
  />
{:else if spec.kind === 'toggle'}
  <PrefToggleField {ctrl} path={spec.path} hint={spec.hint} />
{:else if spec.kind === 'textarea'}
  <PrefTextareaField
    {ctrl}
    path={spec.path}
    rows={spec.rows}
    maxlength={spec.maxlength}
    placeholder={spec.placeholder}
  />
{:else if spec.kind === 'select'}
  <PrefSelectField
    {ctrl}
    path={spec.path}
    options={typeof spec.options === 'function' ? spec.options(draft) : spec.options}
    hint={spec.hintSuffix
      ? [preferenceHint(preferenceFieldMeta(ctrl.fieldSchema, spec.path)), spec.hintSuffix]
          .filter(Boolean)
          .join(' ')
      : undefined}
  />
{:else if spec.kind === 'model'}
  {#if spec.download}
    <div class="grid gap-2">
      <PrefModelPicker
        {ctrl}
        kind={spec.modelKind}
        path={spec.path}
        embedded
        labelled={spec.labelled ?? false}
        emptyFallbackId={spec.emptyFallback
          ? (getPreferenceByPath(draft, spec.emptyFallback) as string | null)
          : null}
      />
      <PrefModelDownload
        {ctrl}
        kind={spec.download}
        modelId={getPreferenceByPath(draft, spec.path) as string | null}
      />
    </div>
  {:else}
    <PrefModelPicker
      {ctrl}
      kind={spec.modelKind}
      path={spec.path}
      embedded
      labelled={spec.labelled ?? false}
      emptyFallbackId={spec.emptyFallback
        ? (getPreferenceByPath(draft, spec.emptyFallback) as string | null)
        : null}
    />
  {/if}
{:else if spec.kind === 'embedder'}
  {@const locked = Boolean(getPreferenceByPath(draft, spec.lockedPath))}
  <div class="grid gap-2">
    <h4 class={HEADING_CLASS}>
      {spec.heading}
      {#if locked}<Badge variant="outline">Locked while indexed</Badge>{/if}
    </h4>
    <PrefModelPicker
      {ctrl}
      kind="embedding"
      path={spec.path}
      embedded
      emptyFallbackId={draft.llm.default_embedder}
      busy={ctrl.busy || locked}
    />
    <PrefModelDownload
      {ctrl}
      kind="embedder"
      modelId={getPreferenceByPath(draft, spec.path) as string | null}
    />
  </div>
{:else if spec.kind === 'tuningProfile'}
  <TuningProfileSelect {ctrl} path={spec.path} scope={spec.scope} />
{:else if spec.kind === 'modelProfile'}
  <ModelWithProfilePair
    {ctrl}
    kind={spec.modelKind}
    modelPath={spec.modelPath}
    profilePath={spec.profilePath}
    scope={spec.scope}
    heading={spec.heading}
    emptyFallbackId={spec.emptyFallback
      ? (getPreferenceByPath(draft, spec.emptyFallback) as string | null)
      : null}
  />
{:else if spec.kind === 'grid'}
  <PrefFieldGrid cols={spec.cols}>
    {#each spec.fields as field, i (i)}
      <PrefFieldRenderer {ctrl} spec={field} />
    {/each}
  </PrefFieldGrid>
{:else if spec.kind === 'column'}
  <div class="grid gap-3">
    {#each spec.fields as field, i (i)}
      <PrefFieldRenderer {ctrl} spec={field} />
    {/each}
  </div>
{:else if spec.kind === 'panel'}
  <PrefPanel {ctrl} title={spec.title} hint={spec.hint}>
    {#each spec.fields as field, i (i)}
      <PrefFieldRenderer {ctrl} spec={field} />
    {/each}
  </PrefPanel>
{:else if spec.kind === 'gated'}
  {@const disabled = spec.disabledWhen(draft)}
  {#if spec.banner && disabled}
    <p
      class="rounded-md border border-border/50 bg-card/45 px-3 py-2 font-sans text-xs text-muted-foreground"
    >
      {spec.banner}
    </p>
  {/if}
  <fieldset {disabled} class={cn('grid gap-4 border-0 p-0', disabled && 'opacity-50')}>
    {#each spec.fields as field, i (i)}
      <PrefFieldRenderer {ctrl} spec={field} />
    {/each}
  </fieldset>
{:else if spec.kind === 'prompt'}
  <div class="grid gap-2">
    {#if spec.heading}
      <h4 class={HEADING_CLASS}>
        {spec.heading}
        {#if spec.headingHelp}<FieldHelp text={spec.headingHelp} />{/if}
      </h4>
    {/if}
    <PromptField
      {ctrl}
      path={spec.path}
      hint={spec.hint}
      ariaLabel={spec.ariaLabel}
      editorLabel={spec.editorLabel}
    />
  </div>
{:else if spec.kind === 'promptLibrary' || spec.kind === 'promptLibrarySelect'}
  <div class="grid gap-2">
    {#if spec.heading}
      <h4 class={HEADING_CLASS}>
        {spec.heading}
        {#if spec.headingHelp}<FieldHelp text={spec.headingHelp} />{/if}
      </h4>
    {/if}
    <ActivePromptLibraryField
      {ctrl}
      dictPath={spec.dictPath}
      activeIdPath={spec.activeIdPath}
      defaultId={spec.defaultId}
      hint={spec.hint}
      ariaLabel={spec.ariaLabel}
      editorLabel={spec.editorLabel}
    />
  </div>
{:else if spec.kind === 'custom'}
  {@const CustomField = CUSTOM_FIELDS[spec.component]}
  <CustomField {ctrl} />
{/if}
