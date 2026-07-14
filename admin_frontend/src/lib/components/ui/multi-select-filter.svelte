<script lang="ts">
  /**
   * Reusable multi-select filter dropdown built on the bits-ui Combobox
   * (type="multiple") — already a project dependency, accessible, searchable.
   *
   * Shape: a summary button ("Label: 5/38") that opens a dropdown containing a
   * search box, Select-all / Clear actions, and a checklist with optional
   * per-option counts. `selected` is a bindable string[] of the CHECKED values.
   *
   * Used for the knowledge-graph edge-type filter, where the relation
   * vocabulary is free-form and can run to dozens of values — too many for
   * inline chips. Styled to match the repo's popover/command tokens.
   */
  import { Combobox } from 'bits-ui';
  import { Check, ChevronsUpDown, Search } from '@lucide/svelte';
  import { cn } from '$lib/utils';
  import { matchesQuery } from '$lib/search/match';
  import { comboboxOpenAtTop } from './combobox-open-top';

  // `keywords` (optional) extends the search match beyond the visible label — e.g. a full id
  // when the label only shows a short form. Matched but not rendered.
  // `tooltip` (optional) is shown as the row's native title on hover — e.g. a longer preview when
  // the label is a one-line summary.
  export type MultiSelectOption = {
    value: string;
    label: string;
    count?: number;
    keywords?: string;
    tooltip?: string;
  };

  let {
    label,
    options,
    selected,
    onSelectedChange,
    searchPlaceholder = 'Search…',
    class: className = ''
  }: {
    label: string;
    options: MultiSelectOption[];
    /** Controlled list of CHECKED values. */
    selected: string[];
    /** Fired with the new checked list on every change (toggle / select-all / clear). */
    onSelectedChange: (values: string[]) => void;
    searchPlaceholder?: string;
    class?: string;
  } = $props();

  let open = $state(false);
  let search = $state('');
  // Anchor the dropdown to the summary button (Combobox anchors to its Input by
  // default; we keep the Input inside the dropdown as the search field instead).
  let triggerRef = $state<HTMLButtonElement | null>(null);
  // Viewport node, so we can force the list to open at the top (bits-ui otherwise scrolls to the
  // first selected item — see comboboxOpenAtTop).
  let viewportRef = $state<HTMLElement | null>(null);
  $effect(() => {
    if (open && viewportRef) return comboboxOpenAtTop(viewportRef);
  });

  const filtered = $derived(
    search.trim() === ''
      ? options
      : options.filter((o) => matchesQuery(`${o.label} ${o.keywords ?? ''}`, search))
  );
  const total = $derived(options.length);
  const summary = $derived(
    selected.length === total ? 'all' : selected.length === 0 ? 'none' : `${selected.length}/${total}`
  );

  function selectAll(): void {
    onSelectedChange(options.map((o) => o.value));
  }
  function clearAll(): void {
    onSelectedChange([]);
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
  <Combobox.Trigger bind:ref={triggerRef}>
    {#snippet child({ props })}
      <button
        {...props}
        type="button"
        aria-label={`Filter ${label}`}
        class={cn(
          'inline-flex h-8 items-center gap-1.5 rounded-md border border-input bg-background px-2.5 text-xs font-medium text-foreground shadow-xs transition-colors hover:bg-accent',
          className
        )}
      >
        <span class="font-semibold text-muted-foreground">{label}</span>
        <span class="tabular-nums">{summary}</span>
        <ChevronsUpDown size={14} class="shrink-0 opacity-50" aria-hidden="true" />
      </button>
    {/snippet}
  </Combobox.Trigger>

  <Combobox.Portal>
    <Combobox.Content
      customAnchor={triggerRef}
      sideOffset={4}
      align="start"
      class="z-50 w-64 origin-(--bits-combobox-content-transform-origin) rounded-lg bg-popover p-1.5 text-sm text-popover-foreground shadow-md ring-1 ring-foreground/10 outline-hidden"
    >
      <!-- Search -->
      <div class="flex items-center gap-2 rounded-md border border-input/40 bg-input/30 px-2">
        <Search size={14} class="shrink-0 opacity-50" aria-hidden="true" />
        <Combobox.Input
          oninput={(e) => (search = e.currentTarget.value)}
          placeholder={searchPlaceholder}
          class="h-8 w-full bg-transparent text-sm outline-hidden placeholder:text-muted-foreground"
        />
      </div>

      <!-- Bulk actions -->
      <div class="mt-1 flex items-center justify-between border-b px-1 pb-1.5 text-xs">
        <span class="text-muted-foreground">{selected.length} / {total} shown</span>
        <div class="flex items-center gap-1">
          <button
            type="button"
            class="rounded px-1.5 py-0.5 font-medium hover:bg-muted disabled:opacity-40"
            disabled={selected.length === total}
            onclick={selectAll}>Select all</button
          >
          <button
            type="button"
            class="rounded px-1.5 py-0.5 font-medium hover:bg-muted disabled:opacity-40"
            disabled={selected.length === 0}
            onclick={clearAll}>Clear</button
          >
        </div>
      </div>

      <!-- Options -->
      <Combobox.Viewport bind:ref={viewportRef} class="mt-1 max-h-64 overflow-auto">
        {#each filtered as opt (opt.value)}
          <Combobox.Item
            value={opt.value}
            label={opt.label}
            title={opt.tooltip}
            class="relative flex cursor-default select-none items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-hidden data-highlighted:bg-muted data-highlighted:text-foreground"
          >
            {#snippet children({ selected: isSelected })}
              <span class="flex size-4 shrink-0 items-center justify-center">
                {#if isSelected}
                  <Check size={14} aria-hidden="true" />
                {/if}
              </span>
              <span class="truncate" title={opt.tooltip}>{opt.label}</span>
              {#if opt.count != null}
                <span class="ml-auto tabular-nums text-xs text-muted-foreground">{opt.count}</span>
              {/if}
            {/snippet}
          </Combobox.Item>
        {:else}
          <div class="px-2 py-3 text-center text-sm text-muted-foreground">No matches</div>
        {/each}
      </Combobox.Viewport>
    </Combobox.Content>
  </Combobox.Portal>
</Combobox.Root>
