<script lang="ts">
  import { goto } from '$app/navigation';
  import { BookOpen, RefreshCw, Settings } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import CharacterResolvedBlock from '$lib/features/characters/sections/CharacterResolvedBlock.svelte';
  import OrderedModelPicker from '$lib/components/ui/ordered-model-picker/OrderedModelPicker.svelte';
  import CharacterSectionCard from '$lib/features/characters/sections/CharacterSectionCard.svelte';
  import {
    characterSectionTitleClass,
    characterSectionHintClass
  } from '$lib/features/characters/shared/character-section-classes';
  import type { CatalogModelRow, CatalogProviderRow } from '$lib/api/catalog';
  import type { CharacterResolvedPayload } from '$lib/api/characters';
  import type { TuningProfile } from '$lib/api/preferences';
  import { formatTuningProfileSummary } from '$lib/catalog/catalog-picker-utils';
  import { preferenceTabHref } from '$lib/features/preferences/shared/preferences-tabs';
  import type { CharacterForm } from '$lib/features/characters/shared/characters-pure';
  import { cn } from '$lib/utils';

  let {
    variant,
    form,
    characterId = undefined,
    catalogModels,
    catalogAllProviders,
    workspaceResolved,
    workspaceActiveIds,
    busy,
    catalogReloadBusy,
    modelPickerResetNonce,
    resolved = null,
    resolvedError = null,
    dirty = false,
    tuningProfiles = {},
    workspaceDefaultTuningProfile = 'balanced_chat',
    onReloadCatalog,
    onDuplicateAttempt,
    markDirty
  }: {
    variant: 'llm' | 'voice';
    form: CharacterForm;
    characterId?: string | null | undefined;
    catalogModels: CatalogModelRow[];
    catalogAllProviders: CatalogProviderRow[];
    workspaceResolved: boolean;
    workspaceActiveIds: Set<string>;
    busy: boolean;
    catalogReloadBusy: boolean;
    modelPickerResetNonce: number;
    resolved?: CharacterResolvedPayload | null;
    resolvedError?: string | null;
    dirty?: boolean;
    tuningProfiles?: Record<string, TuningProfile>;
    workspaceDefaultTuningProfile?: string;
    onReloadCatalog: () => void;
    onDuplicateAttempt: () => void;
    markDirty: () => void;
  } = $props();

  const isLlm = $derived(variant === 'llm');
  const profileEntries = $derived.by(() =>
    Object.entries(tuningProfiles).sort(([, a], [, b]) => a.label.localeCompare(b.label))
  );
  const selectedTuningProfile = $derived(
    form.tuning_profile ? tuningProfiles[form.tuning_profile] : undefined
  );

  const preferencesTuningProfilesHref = preferenceTabHref('tuning-profiles');
</script>

<CharacterSectionCard>
  {#snippet header()}
    <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div class="min-w-0 flex-1">
        {#if isLlm}
          <h4 class={characterSectionTitleClass}>Preferred LLM models</h4>
          <p class={characterSectionHintClass}>
            Select preferred LLM model for this character. You can select multiple fallbacks in order.
          </p>
        {:else}
          <h4 class={characterSectionTitleClass}>Preferred voice models (TTS)</h4>
          <p class={characterSectionHintClass}>
            Select preferred TTS model for this character. You can select multiple fallbacks in order.
          </p>
        {/if}
      </div>
      <!-- Providers/models + reload: shared header for LLM and voice sections (each section renders this block). -->
      <div class="flex shrink-0 flex-wrap items-center justify-end gap-2">
        <Button
          variant="outline"
          size="sm"
          class="shrink-0"
          disabled={busy}
          title="Open Providers/Models (bundled providers and models)"
          onclick={() => void goto('/catalog/')}
        >
          <BookOpen size={14} /> Providers/models
        </Button>
        <Button
          variant="outline"
          size="sm"
          class="shrink-0"
          disabled={busy || catalogReloadBusy}
          title="Reload bundled catalog on the server and refresh model lists"
          onclick={onReloadCatalog}
        >
          <RefreshCw size={14} class={cn(catalogReloadBusy && 'animate-spin')} /> Reload catalog
        </Button>
      </div>
    </div>
  {/snippet}
  {#if isLlm}
    <OrderedModelPicker
      variant="llm"
      bind:selectedIds={form.llm_models}
      catalogModels={catalogModels}
      catalogAllProviders={catalogAllProviders}
      workspaceActiveProvidersResolved={workspaceResolved}
      workspaceActiveProviderIds={workspaceActiveIds}
      {busy}
      resetNonce={modelPickerResetNonce}
      onDuplicateAttempt={onDuplicateAttempt}
      onListChange={markDirty}
    />
    <FormField label="Tuning profile" class="mt-4 max-w-lg">
      <div class="flex items-center gap-2">
        <select
          id="character-tuning-profile"
          class="min-w-0 flex-1"
          value={form.tuning_profile || ''}
          onchange={(event) => {
            form.tuning_profile = event.currentTarget.value;
            markDirty();
          }}
        >
          <option value="">Inherit workspace ({tuningProfiles[workspaceDefaultTuningProfile]?.label ?? 'Default'})</option>
          {#each profileEntries as [id, profile] (id)}
            <option value={id}>{profile.label}</option>
          {/each}
        </select>
        <Button
          variant="outline"
          size="icon"
          class="size-10 shrink-0"
          disabled={busy}
          title="Open workspace settings and scroll to tuning profiles"
          aria-label="Edit tuning profiles in workspace settings"
          onclick={() => void goto(preferencesTuningProfilesHref)}
        >
          <Settings size={16} />
        </Button>
      </div>
      {#if selectedTuningProfile}
        <p class="font-sans text-xs text-muted-foreground">
          {formatTuningProfileSummary(selectedTuningProfile)}
        </p>
      {/if}
    </FormField>
  {:else}
    <OrderedModelPicker
      variant="voice"
      bind:selectedIds={form.voice_models}
      catalogModels={catalogModels}
      catalogAllProviders={catalogAllProviders}
      workspaceActiveProvidersResolved={workspaceResolved}
      workspaceActiveProviderIds={workspaceActiveIds}
      {busy}
      resetNonce={modelPickerResetNonce}
      onDuplicateAttempt={onDuplicateAttempt}
      onListChange={markDirty}
    />
  {/if}

  {#if characterId}
    <div class="mt-6">
      <CharacterResolvedBlock
        resolved={resolved}
        error={resolvedError}
        staleHint={dirty}
        segment={isLlm ? 'llm' : 'voice'}
      />
    </div>
  {/if}
</CharacterSectionCard>
