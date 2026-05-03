<script lang="ts">
  import { goto } from '$app/navigation';
  import { BookOpen, RefreshCw } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import CharacterResolvedBlock from '$lib/features/characters/CharacterResolvedBlock.svelte';
  import OrderedModelPicker from '$lib/components/ui/ordered-model-picker/OrderedModelPicker.svelte';
  import CharacterSectionCard from '$lib/features/characters/CharacterSectionCard.svelte';
  import {
    characterSectionTitleClass,
    characterSectionHintClass
  } from '$lib/features/characters/character-section-classes';
  import type { CatalogModelRow, CatalogProviderRow } from '$lib/api/catalog';
  import type { CharacterResolvedPayload } from '$lib/api/characters';
  import type { CharacterForm } from '$lib/features/characters/utils';
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
    onReloadCatalog: () => void;
    onDuplicateAttempt: () => void;
    markDirty: () => void;
  } = $props();

  const isLlm = $derived(variant === 'llm');
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
      <!-- Model catalog + reload: shared header for LLM and voice sections (each section renders this block). -->
      <div class="flex shrink-0 flex-wrap items-center justify-end gap-2">
        <Button
          variant="outline"
          size="sm"
          class="shrink-0"
          disabled={busy}
          title="Open Model Catalog (bundled providers and models)"
          onclick={() => void goto('/catalog/')}
        >
          <BookOpen size={14} /> Model catalog
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
