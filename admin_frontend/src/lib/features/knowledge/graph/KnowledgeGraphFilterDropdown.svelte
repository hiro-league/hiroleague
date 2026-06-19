<script lang="ts">
  /**
   * Filter dropdown for the knowledge/memory Graph tab — used for BOTH the per-node-type
   * instance filters (Person, Place…) and the edge relation filter.
   *
   * Graph-specific on purpose (NOT the shared MultiSelectFilter): it adds a color-dot
   * select-all/none master toggle, a per-option weight (node connection count / edges-per-relation)
   * with a weight↔alphabetical sort toggle, a clearable search, and an always-visible scrollbar.
   *
   * Built on the bits-ui Combobox (multiple). `selected` is the controlled CHECKED (visible) set.
   */
  import { Combobox } from 'bits-ui';
  import { ArrowDownAZ, ArrowDownWideNarrow, Check, ChevronsUpDown, Search, X } from '@lucide/svelte';
  import { comboboxOpenAtTop } from '$lib/components/ui/combobox-open-top';
  import {
    filterDropdownPlaceholder,
    filterOptionsBySearch,
    filterSelectionSummary,
    sortFilterOptions,
    type GraphFilterOption
  } from './graph-filter-dropdown-helpers';

  // Neutral master-toggle dot when a caller (e.g. edges) has no category color.
  const NEUTRAL_DOT = '#94a3b8';

  let {
    label,
    color = NEUTRAL_DOT,
    options,
    selected,
    note,
    weightNoun = 'connection',
    searchPlaceholder,
    onSelectedChange
  }: {
    label: string;
    /** Master-toggle dot color (e.g. a node-type swatch); neutral grey if omitted. */
    color?: string;
    options: GraphFilterOption[];
    /** Controlled list of CHECKED (visible) values. */
    selected: string[];
    /** Optional perf heads-up shown inside the dropdown for very large lists. */
    note?: string;
    /** Singular noun for the per-row weight tooltip (e.g. 'connection', 'edge'). */
    weightNoun?: string;
    searchPlaceholder?: string;
    onSelectedChange: (values: string[]) => void;
  } = $props();

  let open = $state(false);
  let search = $state('');
  let searchRef = $state<HTMLInputElement | null>(null);
  // Default = heaviest first ("weight"); the toggle flips to A–Z.
  let sortMode = $state<'weight' | 'alpha'>('weight');
  let triggerRef = $state<HTMLButtonElement | null>(null);
  // Viewport node, so we can force the list to open at the top (bits-ui otherwise scrolls to the
  // first selected item — see comboboxOpenAtTop).
  let viewportRef = $state<HTMLElement | null>(null);
  $effect(() => {
    if (open && viewportRef) return comboboxOpenAtTop(viewportRef);
  });

  const sorted = $derived(sortFilterOptions(options, sortMode));
  const filtered = $derived(filterOptionsBySearch(sorted, search));

  const total = $derived(options.length);
  const selectedCount = $derived(selected.length);
  const allSelected = $derived(total > 0 && selectedCount === total);
  const noneSelected = $derived(selectedCount === 0);
  const summary = $derived(filterSelectionSummary(total, selectedCount));
  const placeholder = $derived(filterDropdownPlaceholder(label, searchPlaceholder));

  // The color dot doubles as a select-all / select-none master toggle so the whole group can be
  // flipped without opening the dropdown: fully on → off; otherwise → fully on.
  function toggleAll(e: MouseEvent): void {
    e.stopPropagation();
    onSelectedChange(allSelected ? [] : options.map((o) => o.value));
  }
  function selectAll(): void {
    onSelectedChange(options.map((o) => o.value));
  }
  function clearAll(): void {
    onSelectedChange([]);
  }
  function clearSearch(): void {
    search = '';
    if (searchRef) searchRef.value = '';
    searchRef?.focus();
  }
  function toggleSort(): void {
    sortMode = sortMode === 'alpha' ? 'weight' : 'alpha';
  }
</script>

<Combobox.Root
  type="multiple"
  value={selected}
  onValueChange={onSelectedChange}
  bind:open
  onOpenChangeComplete={(o) => {
    if (!o) search = '';
  }}
>
  <!-- Chip: [dot master-toggle] [trigger: label + summary + chevron] sharing one border. -->
  <div
    class="inline-flex h-8 items-center rounded-md border border-input bg-background text-xs font-medium text-foreground shadow-xs"
  >
    <button
      type="button"
      onclick={toggleAll}
      aria-pressed={allSelected}
      title={allSelected ? `Hide all ${label}` : `Show all ${label}`}
      class="flex h-full items-center rounded-l-md pr-1 pl-2 transition-colors hover:bg-accent"
    >
      <span
        class="size-3 rounded-full border-2 transition-opacity"
        style:border-color={color}
        style:background-color={noneSelected ? 'transparent' : color}
        style:opacity={allSelected || noneSelected ? '1' : '0.55'}
        aria-hidden="true"
      ></span>
    </button>
    <Combobox.Trigger bind:ref={triggerRef}>
      {#snippet child({ props })}
        <button
          {...props}
          type="button"
          aria-label={`Filter ${label}`}
          class="inline-flex h-full items-center gap-1.5 rounded-r-md pr-2 pl-1 transition-colors outline-hidden hover:bg-accent"
        >
          <span class="font-semibold text-muted-foreground">{label}</span>
          <span class="tabular-nums">{summary}</span>
          <ChevronsUpDown size={14} class="shrink-0 opacity-50" aria-hidden="true" />
        </button>
      {/snippet}
    </Combobox.Trigger>
  </div>

  <Combobox.Portal>
    <Combobox.Content
      customAnchor={triggerRef}
      sideOffset={4}
      align="start"
      class="z-50 w-64 origin-(--bits-combobox-content-transform-origin) rounded-lg bg-popover p-1.5 text-sm text-popover-foreground shadow-md ring-1 ring-foreground/10 outline-hidden"
    >
      <!-- Search (with a clear X once there's a query) -->
      <div class="flex items-center gap-2 rounded-md border border-input/40 bg-input/30 px-2">
        <Search size={14} class="shrink-0 opacity-50" aria-hidden="true" />
        <Combobox.Input
          bind:ref={searchRef}
          oninput={(e) => (search = e.currentTarget.value)}
          {placeholder}
          class="h-8 w-full bg-transparent text-sm outline-hidden placeholder:text-muted-foreground"
        />
        {#if search}
          <button
            type="button"
            onclick={clearSearch}
            aria-label="Clear search"
            class="flex size-5 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <X size={14} aria-hidden="true" />
          </button>
        {/if}
      </div>

      <!-- Bulk actions: [sort toggle] Select all / Clear -->
      <div class="mt-1 flex items-center justify-between border-b px-1 pb-1.5 text-xs">
        <span class="text-muted-foreground">{selectedCount} / {total} shown</span>
        <div class="flex items-center gap-1">
          <button
            type="button"
            onclick={toggleSort}
            title={sortMode === 'alpha'
              ? `Sorted A–Z — click to sort by most ${weightNoun}s`
              : `Sorted by most ${weightNoun}s — click to sort A–Z`}
            aria-label="Toggle sort order"
            class="flex size-6 items-center justify-center rounded text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            {#if sortMode === 'alpha'}
              <ArrowDownAZ size={14} aria-hidden="true" />
            {:else}
              <ArrowDownWideNarrow size={14} aria-hidden="true" />
            {/if}
          </button>
          <button
            type="button"
            class="rounded px-1.5 py-0.5 font-medium hover:bg-muted disabled:opacity-40"
            disabled={allSelected}
            onclick={selectAll}>Select all</button
          >
          <button
            type="button"
            class="rounded px-1.5 py-0.5 font-medium hover:bg-muted disabled:opacity-40"
            disabled={noneSelected}
            onclick={clearAll}>Clear</button
          >
        </div>
      </div>

      {#if note}
        <!-- Perf heads-up for very large lists: the list still searches/scrolls all of them. -->
        <p class="mt-1 rounded-sm bg-amber-500/10 px-2 py-1 text-xs text-amber-600 dark:text-amber-400">
          {note}
        </p>
      {/if}

      <!-- Options. Force a visible thin scrollbar: bits-ui's Viewport sets `scrollbar-width: none`
           (higher specificity than the app-wide thin default), so we override THIS instance with an
           important utility rather than a global rule that would touch every other combobox. -->
      <Combobox.Viewport
        bind:ref={viewportRef}
        class="mt-1 max-h-64 overflow-y-auto [scrollbar-width:thin]! [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-muted-foreground/40 [&::-webkit-scrollbar-track]:bg-transparent [&::-webkit-scrollbar]:w-2"
      >
        {#each filtered as opt (opt.value)}
          <Combobox.Item
            value={opt.value}
            label={opt.label}
            class="relative flex cursor-default items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-hidden select-none data-highlighted:bg-muted data-highlighted:text-foreground"
          >
            {#snippet children({ selected: isSelected })}
              <span class="flex size-4 shrink-0 items-center justify-center">
                {#if isSelected}
                  <Check size={14} aria-hidden="true" />
                {/if}
              </span>
              <span class="truncate">{opt.label}</span>
              <span
                class="ml-auto shrink-0 tabular-nums text-xs text-muted-foreground"
                title="{opt.weight} {weightNoun}{opt.weight === 1 ? '' : 's'}"
              >
                {opt.weight}
              </span>
            {/snippet}
          </Combobox.Item>
        {:else}
          <div class="px-2 py-3 text-center text-sm text-muted-foreground">No matches</div>
        {/each}
      </Combobox.Viewport>
    </Combobox.Content>
  </Combobox.Portal>
</Combobox.Root>
