<script lang="ts">
  import type { Snippet } from 'svelte';
  import { Brain, Check, Pencil, Plus, Trash2 } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import FieldHelp from '$lib/components/ui/field-help.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import type { CatalogModelRow, CatalogProviderRow } from '$lib/api/catalog';
  import {
    isThinkingCatalogModel,
    sortCatalogModelsByDateDesc,
    sortCatalogProvidersOnlineFirst
  } from '$lib/catalog/catalog-picker-utils';
  import { cn } from '$lib/utils';

  let {
    label,
    hint,
    selectedId = null,
    catalogModels,
    catalogAllProviders,
    workspaceActiveProvidersResolved,
    workspaceActiveProviderIds,
    busy,
    emptyProviders,
    emptyModelsForProvider,
    onSelect,
    onChange,
    toolbar,
    embedded = false,
    labelled = false
  }: {
    label: string;
    hint: string;
    selectedId?: string | null;
    catalogModels: CatalogModelRow[];
    catalogAllProviders: CatalogProviderRow[];
    workspaceActiveProvidersResolved: boolean;
    workspaceActiveProviderIds: Set<string>;
    busy: boolean;
    emptyProviders: string;
    emptyModelsForProvider: string;
    onSelect: (id: string | null) => void;
    onChange?: () => void;
    /** Optional row (e.g. catalog link + reload) shown under the section title. */
    toolbar?: Snippet;
    /** When true, omit outer card chrome — host `<SectionCardMuted>` owns title/collapse. */
    embedded?: boolean;
    /**
     * When embedded, still render the `label`/`hint` as a FormField-style header.
     * Use when several embedded pickers share ONE host card (so the card title can't
     * stand in for each picker's label) — e.g. the Graphiti model pickers.
     */
    labelled?: boolean;
  } = $props();

  // Dialog selection is staged: the provider/model panes only mutate `pendingId`,
  // and the draft (via onSelect) is touched on Apply — never while browsing.
  let dialogOpen = $state(false);
  let pickProviderId = $state('');
  let pendingId = $state<string | null>(null);

  const providersForPicker = $derived.by(() => {
    const seen = new Set<string>();
    const ids: string[] = [];
    for (const model of catalogModels) {
      const providerId = model.provider_id?.trim();
      if (!providerId || seen.has(providerId)) continue;
      seen.add(providerId);
      ids.push(providerId);
    }
    const rows = ids.map((id) => {
      const row = catalogAllProviders.find((provider) => provider.id === id);
      return { id, display_name: row?.display_name?.trim() ? row.display_name : id };
    });
    return sortCatalogProvidersOnlineFirst(rows, providerConfigured);
  });

  const modelsForPicker = $derived(
    sortCatalogModelsByDateDesc(catalogModels.filter((model) => model.provider_id === pickProviderId))
  );

  const selectedRow = $derived(
    selectedId ? catalogModels.find((model) => model.id === selectedId) : undefined
  );

  function providerConfigured(providerId: string): boolean {
    return !workspaceActiveProvidersResolved || workspaceActiveProviderIds.has(providerId);
  }

  function selectedRowInactive(meta: CatalogModelRow | undefined): boolean {
    return (
      workspaceActiveProvidersResolved &&
      !!meta?.provider_id &&
      !workspaceActiveProviderIds.has(meta.provider_id)
    );
  }

  function openDialog() {
    // Seed the staged state from the current default so Edit lands on the right pane.
    pendingId = selectedId;
    pickProviderId = selectedRow?.provider_id ?? '';
    dialogOpen = true;
  }

  function applyDialog() {
    onSelect(pendingId);
    onChange?.();
    dialogOpen = false;
  }

  function clearModel() {
    onSelect(null);
    onChange?.();
  }
</script>

{#snippet selectedCard()}
  {#if selectedId}
    {@const inactive = selectedRowInactive(selectedRow)}
    <div class="flex items-center gap-3 rounded-md border border-input bg-card/65 p-3">
      <span
        class={cn(
          'size-2 shrink-0 rounded-full shadow-sm ring-2 ring-background',
          workspaceActiveProvidersResolved
            ? inactive
              ? 'bg-red-500'
              : 'bg-emerald-500'
            : 'bg-muted-foreground/40'
        )}
        title={inactive ? 'Provider is not configured in Active Providers.' : 'Provider is configured.'}
        aria-hidden="true"
      ></span>
      <span class="min-w-0 flex-1 grid gap-0.5">
        <code class="break-all font-mono text-sm font-medium leading-snug text-foreground">
          {selectedId}
        </code>
        {#if selectedRow}
          <span class="flex items-center gap-1.5 font-sans text-xs text-muted-foreground">
            <span class="truncate">{selectedRow.display_name}</span>
            {#if isThinkingCatalogModel(selectedRow)}
              <Brain
                size={13}
                class="shrink-0 text-violet-600 dark:text-violet-400"
                aria-label="Reasoning model"
                title="Reasoning / thinking model"
              />
            {/if}
          </span>
        {/if}
      </span>
      <Button
        variant="outline"
        size="sm"
        class="shrink-0"
        disabled={busy}
        aria-label={`Edit ${label}`}
        title="Change model"
        onclick={openDialog}
      >
        <Pencil size={14} />
        Edit
      </Button>
      <Button
        variant="ghost"
        size="icon"
        class="size-9 shrink-0 text-destructive hover:text-destructive"
        disabled={busy}
        aria-label={`Clear ${label}`}
        title="Clear default"
        onclick={clearModel}
      >
        <Trash2 size={17} />
      </Button>
    </div>
  {:else}
    <div
      class="flex items-center justify-between gap-3 rounded-md border border-dashed border-input bg-background/40 p-3"
    >
      <p class="text-sm text-muted-foreground">No workspace default set.</p>
      <Button
        variant="outline"
        size="sm"
        class="shrink-0"
        disabled={busy}
        aria-label={`Add ${label}`}
        title="Select a model"
        onclick={openDialog}
      >
        <Plus size={14} />
        Add model
      </Button>
    </div>
  {/if}
{/snippet}

{#if embedded}
  <div class="grid gap-2">
    {#if labelled && label?.trim()}
      <h4
        class="inline-flex items-center gap-1.5 font-sans text-base font-semibold leading-snug text-foreground"
      >
        {label}
        {#if hint?.trim()}
          <FieldHelp text={hint} />
        {/if}
      </h4>
    {/if}
    {@render selectedCard()}
  </div>
{:else}
  <section class="grid gap-3 rounded-md border border-border/70 bg-background/45 p-4">
    <div class="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
      <div class="grid min-w-0 gap-1">
        <h4 class="font-sans text-base font-semibold text-foreground">{label}</h4>
        <p class="text-sm text-muted-foreground">{hint}</p>
      </div>
      {#if toolbar}
        <div class="flex shrink-0 flex-wrap items-center justify-end gap-2">
          {@render toolbar()}
        </div>
      {/if}
    </div>
    {@render selectedCard()}
  </section>
{/if}

<Dialog.Root open={dialogOpen} onOpenChange={(next) => (dialogOpen = next)}>
  <Dialog.Content class="sm:max-w-3xl">
    <Dialog.Header>
      <Dialog.Title>{selectedId ? 'Change' : 'Select'} {label}</Dialog.Title>
      {#if hint?.trim()}
        <Dialog.Description>{hint}</Dialog.Description>
      {/if}
    </Dialog.Header>

    <div class="flex flex-col gap-4 sm:flex-row sm:items-start">
      <div class="grid min-w-0 gap-2 content-start sm:w-[16rem] sm:shrink-0">
        <span class="font-sans text-sm font-semibold text-muted-foreground">Provider</span>
        <div
          class="h-[20rem] overflow-y-auto rounded-md border border-input bg-background"
          role="listbox"
          aria-label={`${label} providers`}
        >
          {#each providersForPicker as provider (provider.id)}
            {@const providerOk = providerConfigured(provider.id)}
            <button
              type="button"
              role="option"
              aria-selected={pickProviderId === provider.id}
              title={providerOk ? 'Provider configured in this workspace.' : 'Provider is not configured in Active Providers.'}
              class={cn(
                'flex w-full items-center gap-2.5 border-b border-border/60 px-3 py-2 text-left font-sans text-sm font-medium transition-colors last:border-b-0 hover:bg-accent/60',
                pickProviderId === provider.id && 'bg-primary/15 text-foreground'
              )}
              onclick={() => {
                pickProviderId = provider.id;
              }}
            >
              <span
                class={cn(
                  'size-2 shrink-0 rounded-full shadow-sm ring-2 ring-background',
                  workspaceActiveProvidersResolved
                    ? providerOk
                      ? 'bg-emerald-500'
                      : 'bg-red-500'
                    : 'bg-muted-foreground/40'
                )}
                aria-hidden="true"
              ></span>
              <span class="min-w-0 flex-1 truncate">{provider.display_name}</span>
            </button>
          {:else}
            <p class="px-3 py-4 text-sm text-muted-foreground">{emptyProviders}</p>
          {/each}
        </div>
      </div>

      <div class="grid min-w-0 flex-1 gap-2 content-start">
        <span class="font-sans text-sm font-semibold text-muted-foreground">Model</span>
        <div
          class="h-[20rem] overflow-y-auto rounded-md border border-input bg-background"
          aria-label={`${label} models`}
        >
          {#if !pickProviderId}
            <p class="px-3 py-4 text-sm text-muted-foreground">Select a provider.</p>
          {:else}
            {#each modelsForPicker as model (model.id)}
              <div class="flex items-center gap-2 border-b border-border/60 px-2 py-1.5 last:border-b-0">
                <span class="min-w-0 flex-1 grid gap-0.5">
                  <span class="flex min-w-0 items-center gap-1.5 truncate font-sans text-sm text-foreground" title={model.id}>
                    <span class="truncate">{model.display_name}</span>
                    {#if isThinkingCatalogModel(model)}
                      <Brain
                        size={14}
                        class="shrink-0 text-violet-600 dark:text-violet-400"
                        aria-label="Reasoning model"
                        title="Reasoning / thinking model"
                      />
                    {/if}
                  </span>
                  <code class="truncate font-mono text-xs text-muted-foreground">{model.id}</code>
                </span>
                <Button
                  variant={pendingId === model.id ? 'default' : 'outline'}
                  size="icon"
                  class="size-8 shrink-0"
                  disabled={busy}
                  aria-label={`Pick ${model.display_name}`}
                  title="Pick this model"
                  onclick={() => (pendingId = model.id)}
                >
                  {#if pendingId === model.id}
                    <Check size={15} />
                  {:else}
                    <Plus size={15} />
                  {/if}
                </Button>
              </div>
            {:else}
              <p class="px-3 py-4 text-sm text-muted-foreground">{emptyModelsForProvider}</p>
            {/each}
          {/if}
        </div>
      </div>
    </div>

    <Dialog.Footer>
      <Button variant="outline" onclick={() => (dialogOpen = false)}>Cancel</Button>
      <Button disabled={busy || !pendingId || pendingId === selectedId} onclick={applyDialog}>
        {selectedId ? 'Apply' : 'Add'}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
