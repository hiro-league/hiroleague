<script lang="ts">
  import type { Snippet } from 'svelte';
  import { Check, Plus, Trash2 } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import type { CatalogModelRow, CatalogProviderRow } from '$lib/api/catalog';
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
    toolbar
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
  } = $props();

  let pickProviderId = $state('');

  const providersForPicker = $derived.by(() => {
    const seen = new Set<string>();
    const ids: string[] = [];
    for (const model of catalogModels) {
      const providerId = model.provider_id?.trim();
      if (!providerId || seen.has(providerId)) continue;
      seen.add(providerId);
      ids.push(providerId);
    }
    ids.sort((a, b) => a.localeCompare(b));
    return ids.map((id) => {
      const row = catalogAllProviders.find((provider) => provider.id === id);
      return { id, display_name: row?.display_name?.trim() ? row.display_name : id };
    });
  });

  const modelsForPicker = $derived(
    catalogModels
      .filter((model) => model.provider_id === pickProviderId)
      .slice()
      .sort((a, b) => a.display_name.localeCompare(b.display_name))
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

  function chooseModel(id: string) {
    onSelect(id);
    onChange?.();
  }

  function clearModel() {
    onSelect(null);
    onChange?.();
  }
</script>

<section class="grid gap-3 rounded-md border border-border/70 bg-background/45 p-4">
  <div class="grid gap-2">
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
  </div>

  <div class="flex flex-col gap-4 xl:flex-row xl:items-start">
    <div class="grid min-w-0 gap-2 content-start xl:w-[16rem] xl:shrink-0">
      <span class="font-sans text-sm font-semibold text-muted-foreground">Provider</span>
      <div
        class="max-h-[12rem] overflow-y-auto rounded-md border border-input bg-background"
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

    <div class="grid min-w-0 gap-2 content-start xl:w-[20rem] xl:shrink-0">
      <span class="font-sans text-sm font-semibold text-muted-foreground">Model</span>
      <div
        class="max-h-[12rem] overflow-y-auto rounded-md border border-input bg-background"
        aria-label={`${label} models`}
      >
        {#if !pickProviderId}
          <p class="px-3 py-4 text-sm text-muted-foreground">Select a provider.</p>
        {:else}
          {#each modelsForPicker as model (model.id)}
            <div class="flex items-center gap-2 border-b border-border/60 px-2 py-1.5 last:border-b-0">
              <span class="min-w-0 flex-1 grid gap-0.5">
                <span class="truncate font-sans text-sm text-foreground" title={model.id}>
                  {model.display_name}
                </span>
                <code class="truncate font-mono text-xs text-muted-foreground">{model.id}</code>
              </span>
              <Button
                variant={selectedId === model.id ? 'default' : 'outline'}
                size="icon"
                class="size-8 shrink-0"
                disabled={busy}
                aria-label={`Use ${model.display_name}`}
                title="Use this model"
                onclick={() => chooseModel(model.id)}
              >
                {#if selectedId === model.id}
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

    <div class="grid min-w-0 flex-1 gap-2">
      <span class="font-sans text-sm font-semibold text-muted-foreground">Current default</span>
      <div class="min-h-[6rem] rounded-md border border-input bg-card/65 p-3">
        {#if selectedId}
          {@const inactive = selectedRowInactive(selectedRow)}
          <div class="flex items-start gap-3">
            <span
              class={cn(
                'mt-1.5 size-2 shrink-0 rounded-full shadow-sm ring-2 ring-background',
                workspaceActiveProvidersResolved
                  ? inactive
                    ? 'bg-red-500'
                    : 'bg-emerald-500'
                  : 'bg-muted-foreground/40'
              )}
              title={inactive ? 'Provider is not configured in Active Providers.' : 'Provider is configured.'}
              aria-hidden="true"
            ></span>
            <span class="min-w-0 flex-1 grid gap-1">
              <code class="break-all font-mono text-sm font-medium leading-snug text-foreground">
                {selectedId}
              </code>
              {#if selectedRow}
                <span class="font-sans text-sm text-muted-foreground">{selectedRow.display_name}</span>
              {/if}
            </span>
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
          <p class="py-5 text-center text-sm text-muted-foreground">No workspace default set.</p>
        {/if}
      </div>
    </div>
  </div>
</section>
