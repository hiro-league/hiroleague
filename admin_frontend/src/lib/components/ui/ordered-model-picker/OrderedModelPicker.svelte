<script lang="ts">
  import { ArrowRight, GripVertical, Plus, Trash2 } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import type { CatalogModelRow, CatalogProviderRow } from '$lib/api/catalog';
  import { createCatalogModelDragGhost } from '$lib/components/ui/ordered-model-picker/drag-ghost';
  import { cn } from '$lib/utils';

  const VARIANT_COPY = {
    llm: {
      providerListAria: 'Catalog providers with chat models',
      modelListAria: 'Chat models for selected provider',
      selectedListAria: 'Preferred LLM models in order',
      emptyProviders: 'No chat providers in catalog.',
      emptyModelsForProvider: 'No chat models for this provider.',
      emptySelected: 'None — workspace default chat applies.',
      providerOnlineTitle: 'Online — configured for chat in this workspace.',
      providerOfflineTitle: 'Offline — not configured under Active Providers (no chat credentials).',
      selectedOnlineTitle: 'Online — provider configured for chat in this workspace.',
      selectedOfflineTitle: 'Offline — provider not configured under Active Providers.',
      addAriaLabel: (displayName: string) => `Add ${displayName} to preferred list`
    },
    voice: {
      providerListAria: 'Catalog providers with TTS models',
      modelListAria: 'TTS models for selected provider',
      selectedListAria: 'Preferred voice models in order',
      emptyProviders: 'No voice-capable providers in catalog.',
      emptyModelsForProvider: 'No TTS/STT models for this provider.',
      emptySelected: 'None — workspace default TTS applies.',
      providerOnlineTitle: 'Online — configured for TTS in this workspace.',
      providerOfflineTitle: 'Offline — not configured under Active Providers (no TTS credentials).',
      selectedOnlineTitle: 'Online — provider configured for TTS in this workspace.',
      selectedOfflineTitle: 'Offline — provider not configured under Active Providers.',
      addAriaLabel: (displayName: string) => `Add ${displayName} to preferred voice list`
    }
  } as const;

  let {
    variant,
    catalogModels,
    catalogAllProviders,
    selectedIds = $bindable<string[]>([]),
    workspaceActiveProvidersResolved,
    workspaceActiveProviderIds,
    busy,
    /** Bump when parent resets pickers (new character / loaded edit form). */
    resetNonce = 0,
    onDuplicateAttempt,
    onListChange
  }: {
    variant: keyof typeof VARIANT_COPY;
    catalogModels: CatalogModelRow[];
    catalogAllProviders: CatalogProviderRow[];
    selectedIds?: string[];
    workspaceActiveProvidersResolved: boolean;
    workspaceActiveProviderIds: Set<string>;
    busy: boolean;
    resetNonce?: number;
    onDuplicateAttempt?: () => void;
    onListChange?: () => void;
  } = $props();

  const copy = $derived(VARIANT_COPY[variant]);

  let pickProviderId = $state('');
  let dragFromIndex = $state<number | null>(null);
  let dropInsertAt = $state<number | null>(null);
  let dragGhostEl: HTMLDivElement | null = null;

  $effect(() => {
    void resetNonce;
    pickProviderId = '';
  });

  const providersForPicker = $derived.by(() => {
    const seen = new Set<string>();
    const ids: string[] = [];
    for (const m of catalogModels) {
      const pid = m.provider_id?.trim();
      if (!pid || seen.has(pid)) continue;
      seen.add(pid);
      ids.push(pid);
    }
    ids.sort((a, b) => a.localeCompare(b));
    return ids.map((id) => {
      const row = catalogAllProviders.find((p) => p.id === id);
      return { id, display_name: row?.display_name?.trim() ? row.display_name : id };
    });
  });

  const modelsForPicker = $derived(
    catalogModels
      .filter((m) => m.provider_id === pickProviderId)
      .slice()
      .sort((a, b) => a.display_name.localeCompare(b.display_name))
  );

  function catalogRow(canonicalId: string): CatalogModelRow | undefined {
    return catalogModels.find((m) => m.id === canonicalId);
  }

  function emitChange() {
    onListChange?.();
  }

  function addToBucket(canonicalId: string) {
    const id = canonicalId.trim();
    if (!id) return;
    if (selectedIds.includes(id)) {
      onDuplicateAttempt?.();
      return;
    }
    selectedIds = [...selectedIds, id];
    emitChange();
  }

  function removeFromBucket(canonicalId: string) {
    selectedIds = selectedIds.filter((x) => x !== canonicalId);
    emitChange();
  }

  /** Insert moved row before ``insertBeforeOriginal`` in the pre-drag order (0…length). */
  function reorderToGap(fromIndex: number, insertBeforeOriginal: number) {
    const len = selectedIds.length;
    if (fromIndex < 0 || fromIndex >= len || insertBeforeOriginal < 0 || insertBeforeOriginal > len) return;
    const next = [...selectedIds];
    const [item] = next.splice(fromIndex, 1);
    let to = insertBeforeOriginal;
    if (fromIndex < insertBeforeOriginal) {
      to--;
    }
    next.splice(to, 0, item!);
    selectedIds = next;
    emitChange();
  }

  function onHandleDragStart(e: DragEvent, index: number) {
    dragFromIndex = index;
    e.dataTransfer?.setData('text/plain', String(index));
    e.dataTransfer!.effectAllowed = 'move';

    const mid = selectedIds[index];
    const meta = catalogRow(mid);
    const ghost = createCatalogModelDragGhost(mid, meta?.display_name);
    dragGhostEl = ghost;
    e.dataTransfer?.setDragImage(ghost, 16, 16);
  }

  function onRowDragOver(e: DragEvent, idx: number) {
    e.preventDefault();
    if (dragFromIndex === null) return;
    e.dataTransfer!.dropEffect = 'move';
    const el = e.currentTarget as HTMLElement;
    const rect = el.getBoundingClientRect();
    const before = e.clientY < rect.top + rect.height / 2;
    dropInsertAt = before ? idx : idx + 1;
  }

  function onRowDrop(e: DragEvent) {
    e.preventDefault();
    const raw = e.dataTransfer?.getData('text/plain') ?? '';
    const from = raw !== '' ? Number.parseInt(raw, 10) : (dragFromIndex ?? -1);
    const insertAt = dropInsertAt;
    if (
      Number.isNaN(from) ||
      from < 0 ||
      insertAt === null ||
      insertAt < 0 ||
      insertAt > selectedIds.length
    ) {
      onDragEnd();
      return;
    }
    reorderToGap(from, insertAt);
    onDragEnd();
  }

  function onDragEnd() {
    dragGhostEl?.remove();
    dragGhostEl = null;
    dragFromIndex = null;
    dropInsertAt = null;
  }

  function providerConfigured(providerId: string): boolean {
    return !workspaceActiveProvidersResolved || workspaceActiveProviderIds.has(providerId);
  }

  function selectedRowInactive(meta: CatalogModelRow | undefined): boolean {
    return (
      workspaceActiveProvidersResolved &&
      !!(meta?.provider_id) &&
      !workspaceActiveProviderIds.has(meta.provider_id)
    );
  }
</script>

<div class="flex flex-col gap-6 lg:flex-row lg:items-start lg:gap-2">
  <div class="grid min-w-0 gap-2 content-start lg:w-[20rem] lg:max-w-full lg:shrink-0">
    <span class="font-sans text-sm font-semibold text-muted-foreground">Provider</span>
    <div
      class="llm-picker-scroll max-h-[12.5rem] overflow-y-auto rounded-md border border-input bg-background"
      role="listbox"
      aria-label={copy.providerListAria}
    >
      {#each providersForPicker as p (p.id)}
        {@const provOk = providerConfigured(p.id)}
        <button
          type="button"
          role="option"
          aria-selected={pickProviderId === p.id}
          title={provOk ? copy.providerOnlineTitle : copy.providerOfflineTitle}
          class={cn(
            'flex w-full items-center gap-2.5 px-3 py-2 text-left font-sans text-sm font-medium transition-colors',
            'border-b border-border/60 last:border-b-0 hover:bg-accent/60',
            pickProviderId === p.id && 'bg-primary/15 text-foreground'
          )}
          onclick={() => {
            pickProviderId = p.id;
          }}
        >
          {#if workspaceActiveProvidersResolved}
            <span
              class={cn(
                'size-2 shrink-0 rounded-full shadow-sm ring-2 ring-background',
                provOk ? 'bg-emerald-500' : 'bg-red-500'
              )}
              aria-hidden="true"
            ></span>
          {:else}
            <span
              class="size-2 shrink-0 rounded-full bg-muted-foreground/40 ring-2 ring-background"
              title="Unknown — could not load workspace Active Providers."
              aria-hidden="true"
            ></span>
          {/if}
          <span class="min-w-0 flex-1 truncate">{p.display_name}</span>
        </button>
      {:else}
        <p class="px-3 py-4 text-sm text-muted-foreground">{copy.emptyProviders}</p>
      {/each}
    </div>
  </div>

  <div
    class="hidden shrink-0 text-primary lg:mt-7 lg:flex lg:w-8 lg:flex-col lg:items-center"
    aria-hidden="true"
  >
    <Plus size={18} strokeWidth={2.5} />
  </div>

  <div class="grid min-w-0 gap-2 content-start lg:w-[20rem] lg:max-w-full lg:shrink-0">
    <span class="font-sans text-sm font-semibold text-muted-foreground">Model</span>
    <div
      class="llm-picker-scroll max-h-[12.5rem] overflow-y-auto rounded-md border border-input bg-background"
      aria-label={copy.modelListAria}
    >
      {#if !pickProviderId}
        <p class="px-3 py-4 text-sm text-muted-foreground">Select a provider.</p>
      {:else}
        {#each modelsForPicker as m (m.id)}
          <div class="flex items-center gap-1 border-b border-border/60 px-2 py-1.5 last:border-b-0">
            <span class="min-w-0 flex-1 truncate font-sans text-sm text-foreground" title={m.id}>
              {m.display_name}
            </span>
            <Button
              variant="outline"
              size="icon"
              class="size-8 shrink-0"
              disabled={busy}
              aria-label={copy.addAriaLabel(m.display_name)}
              title="Add to list"
              onclick={() => addToBucket(m.id)}
            >
              <Plus size={15} />
            </Button>
          </div>
        {:else}
          <p class="px-3 py-4 text-sm text-muted-foreground">{copy.emptyModelsForProvider}</p>
        {/each}
      {/if}
    </div>
  </div>

  <div
    class="hidden shrink-0 text-primary lg:mt-7 lg:flex lg:w-8 lg:flex-col lg:items-center"
    aria-hidden="true"
  >
    <ArrowRight size={18} strokeWidth={2.5} />
  </div>

  <div class="grid min-w-0 flex-1 gap-2 content-start lg:min-w-0">
    <span class="font-sans text-sm font-semibold text-muted-foreground"
      >Selected (order = preference)</span
    >
    <ul
      class="llm-picker-scroll max-h-[12.5rem] space-y-1 overflow-y-auto rounded-md border border-input bg-background/45 p-1.5"
      aria-label={copy.selectedListAria}
      ondragover={(e) => {
        if (selectedIds.length === 0 && dragFromIndex !== null) {
          e.preventDefault();
          const dt = e.dataTransfer;
          if (dt) dt.dropEffect = 'move';
          dropInsertAt = 0;
        }
      }}
      ondrop={(e) => {
        if (selectedIds.length === 0) onRowDrop(e);
      }}
    >
      {#each selectedIds as mid, idx (mid)}
        {#if dropInsertAt === idx}
          <li class="pointer-events-none list-none py-0.5" aria-hidden="true">
            <div
              class="h-1 rounded-full bg-primary shadow-[0_0_10px_color-mix(in_oklab,var(--primary)_55%,transparent)]"
            ></div>
          </li>
        {/if}
        {@const meta = catalogRow(mid)}
        {@const rowInactive = selectedRowInactive(meta)}
        <li
          class={cn(
            'llm-selected-row flex items-center gap-2 rounded-md border border-border/50 bg-card px-2 py-1.5 shadow-sm transition-opacity',
            dragFromIndex === idx && 'opacity-45'
          )}
          ondragover={(e) => onRowDragOver(e, idx)}
          ondrop={onRowDrop}
        >
          <button
            type="button"
            class="flex size-10 shrink-0 cursor-grab touch-none items-center justify-center rounded-md border border-transparent text-muted-foreground hover:bg-accent active:cursor-grabbing"
            draggable="true"
            aria-label={`Drag to reorder ${mid}`}
            title="Drag to reorder"
            ondragstart={(e) => onHandleDragStart(e, idx)}
            ondragend={onDragEnd}
          >
            <GripVertical size={18} aria-hidden="true" />
          </button>
          {#if workspaceActiveProvidersResolved}
            <span
              class={cn(
                'size-2 shrink-0 rounded-full shadow-sm ring-2 ring-background',
                rowInactive ? 'bg-red-500' : 'bg-emerald-500'
              )}
              title={rowInactive ? copy.selectedOfflineTitle : copy.selectedOnlineTitle}
              aria-hidden="true"
            ></span>
          {:else}
            <span
              class="size-2 shrink-0 rounded-full bg-muted-foreground/40 ring-2 ring-background"
              title="Unknown — could not load workspace Active Providers."
              aria-hidden="true"
            ></span>
          {/if}
          <span class="min-w-0 flex-1 grid gap-1">
            <code class="break-all font-mono text-sm font-medium leading-snug text-foreground">{mid}</code>
            {#if meta}
              <span class="font-sans text-sm text-muted-foreground">{meta.display_name}</span>
            {/if}
          </span>
          <Button
            variant="ghost"
            size="icon"
            class="size-10 shrink-0 text-destructive hover:text-destructive"
            aria-label={`Remove ${mid} from list`}
            onclick={() => removeFromBucket(mid)}
          >
            <Trash2 size={18} />
          </Button>
        </li>
      {:else}
        <li class="px-2 py-6 text-center font-sans text-sm text-muted-foreground">
          {copy.emptySelected}
        </li>
      {/each}
      {#if dropInsertAt === selectedIds.length && selectedIds.length > 0}
        <li class="pointer-events-none list-none py-0.5" aria-hidden="true">
          <div
            class="h-1 rounded-full bg-primary shadow-[0_0_10px_color-mix(in_oklab,var(--primary)_55%,transparent)]"
          ></div>
        </li>
      {/if}
    </ul>
  </div>
</div>
