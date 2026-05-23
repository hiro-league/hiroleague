<script lang="ts">
  import { tick } from 'svelte';
  import { LoaderCircle, Plus, X } from '@lucide/svelte';
  import { cn } from '$lib/utils';

  type TagOption = { id: number; name: string };

  let {
    options,
    selected = $bindable<string[]>([]),
    placeholder = 'Search or create tags…',
    disabled = false,
    creating = false,
    class: className = '',
    onCreate
  }: {
    options: TagOption[];
    selected?: string[];
    placeholder?: string;
    disabled?: boolean;
    creating?: boolean;
    class?: string;
    onCreate: (name: string) => Promise<{ name: string } | void>;
  } = $props();

  let open = $state(false);
  let search = $state('');
  let inputEl = $state<HTMLInputElement | null>(null);
  let rootEl = $state<HTMLDivElement | null>(null);

  const trimmedSearch = $derived(search.trim());
  const normalizedSearch = $derived(trimmedSearch.toLowerCase());

  function namesEqual(a: string, b: string) {
    return a.localeCompare(b, undefined, { sensitivity: 'accent' }) === 0;
  }

  function isSelected(name: string) {
    return selected.some((tag) => namesEqual(tag, name));
  }

  const availableOptions = $derived(options.filter((option) => !isSelected(option.name)));

  const filteredOptions = $derived(
    normalizedSearch
      ? availableOptions.filter((option) => option.name.toLowerCase().includes(normalizedSearch))
      : availableOptions
  );

  const showCreate = $derived(
    trimmedSearch.length > 0 &&
      !options.some((option) => namesEqual(option.name, trimmedSearch)) &&
      !isSelected(trimmedSearch)
  );

  function addTag(name: string) {
    const clean = name.trim();
    if (!clean || isSelected(clean)) return;
    selected = [...selected, clean];
    search = '';
  }

  function removeTag(name: string) {
    selected = selected.filter((tag) => !namesEqual(tag, name));
  }

  function removeLastTag() {
    if (selected.length === 0) return;
    selected = selected.slice(0, -1);
  }

  async function commitSearch() {
    if (!trimmedSearch || creating) return;
    const existing = options.find((option) => namesEqual(option.name, trimmedSearch));
    if (existing) {
      addTag(existing.name);
      return;
    }
    if (isSelected(trimmedSearch)) {
      search = '';
      return;
    }
    const created = await onCreate(trimmedSearch);
    addTag(created?.name ?? trimmedSearch);
  }

  async function focusInput() {
    await tick();
    inputEl?.focus();
  }

  function handleInputFocus() {
    if (disabled) return;
    open = true;
  }

  function handleFieldPointerDown() {
    if (disabled) return;
    open = true;
    void focusInput();
  }

  function keepFocus(event: MouseEvent) {
    // Prevent input blur before click so suggestion picks register reliably.
    event.preventDefault();
  }

  async function handleInputKeydown(event: KeyboardEvent) {
    if (event.key === 'Enter') {
      event.preventDefault();
      if (filteredOptions.length === 1 && !showCreate) {
        addTag(filteredOptions[0].name);
        return;
      }
      await commitSearch();
      return;
    }
    if (event.key === 'Backspace' && !search && selected.length > 0) {
      event.preventDefault();
      removeLastTag();
      return;
    }
    if (event.key === 'Escape') {
      event.preventDefault();
      open = false;
      return;
    }
    if (event.key === ',') {
      event.preventDefault();
      await commitSearch();
    }
  }

  async function selectSuggestion(name: string) {
    addTag(name);
    open = true;
    await focusInput();
  }

  async function selectCreate() {
    await commitSearch();
    open = true;
    await focusInput();
  }

  $effect(() => {
    if (!open) return;
    const handlePointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (target && rootEl?.contains(target)) return;
      open = false;
    };
    document.addEventListener('pointerdown', handlePointerDown);
    return () => document.removeEventListener('pointerdown', handlePointerDown);
  });
</script>

<div bind:this={rootEl} class={cn('relative w-full', className)}>
  <div
    role="combobox"
    aria-expanded={open}
    aria-haspopup="listbox"
    aria-disabled={disabled}
    class={cn(
      'flex min-h-9 w-full flex-wrap items-center gap-1 rounded-md border bg-background px-2 py-1 shadow-xs outline-none focus-within:ring-2 focus-within:ring-primary',
      disabled && 'cursor-not-allowed opacity-50'
    )}
    onclick={handleFieldPointerDown}
    onkeydown={(event) => {
      if (event.key === 'Backspace' && event.target === event.currentTarget && selected.length > 0) {
        event.preventDefault();
        removeLastTag();
      }
    }}
  >
    {#each selected as tag, index (tag + index)}
      <span
        class="inline-flex max-w-full items-center gap-1 rounded-md border border-primary bg-primary/10 px-2 py-0.5 font-sans text-xs text-foreground"
      >
        <span class="truncate">{tag}</span>
        <button
          class="inline-flex size-5 shrink-0 items-center justify-center rounded-sm text-muted-foreground hover:bg-background/80 hover:text-foreground"
          type="button"
          data-tag-remove
          aria-label={`Remove tag ${tag}`}
          {disabled}
          onclick={(event) => {
            event.stopPropagation();
            removeTag(tag);
            void focusInput();
          }}
        >
          <X size={12} />
        </button>
      </span>
    {/each}
    <input
      bind:this={inputEl}
      bind:value={search}
      class="min-w-[8rem] flex-1 border-0 bg-transparent px-1 py-1 font-sans text-sm outline-none disabled:cursor-not-allowed"
      type="text"
      {placeholder}
      {disabled}
      aria-label="Add tags"
      onfocus={handleInputFocus}
      onkeydown={handleInputKeydown}
    />
    {#if creating}
      <LoaderCircle size={14} class="mr-1 shrink-0 animate-spin text-muted-foreground" />
    {/if}
  </div>
  {#if open}
    <div
      class="absolute top-[calc(100%+0.25rem)] z-50 w-full overflow-hidden rounded-md border bg-popover text-popover-foreground shadow-md"
      role="listbox"
      aria-label="Tag suggestions"
      onmousedown={keepFocus}
    >
      <div class="max-h-56 overflow-y-auto p-1">
        {#if filteredOptions.length === 0 && !showCreate}
          <div class="px-2 py-3 text-center font-sans text-sm text-muted-foreground">
            {options.length === 0 ? 'Type to create your first tag' : 'No matching tags'}
          </div>
        {/if}
        {#if filteredOptions.length > 0}
          <div class="px-2 py-1.5 font-sans text-xs font-medium text-muted-foreground">
            {trimmedSearch ? 'Matches' : 'Existing tags'}
          </div>
          {#each filteredOptions as option (option.id)}
            <button
              class="flex w-full rounded-sm px-2 py-1.5 text-left font-sans text-sm hover:bg-muted"
              type="button"
              role="option"
              onclick={() => void selectSuggestion(option.name)}
            >
              {option.name}
            </button>
          {/each}
        {/if}
        {#if showCreate}
          <button
            class="flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left font-sans text-sm hover:bg-muted disabled:opacity-50"
            type="button"
            disabled={creating}
            onclick={() => void selectCreate()}
          >
            {#if creating}
              <LoaderCircle size={14} class="animate-spin" />
            {:else}
              <Plus size={14} />
            {/if}
            Create "{trimmedSearch}"
          </button>
        {/if}
      </div>
    </div>
  {/if}
</div>
