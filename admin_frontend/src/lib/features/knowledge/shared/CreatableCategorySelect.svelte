<script lang="ts">
  import { tick } from 'svelte';
  import { ChevronsUpDown, LoaderCircle, Plus } from '@lucide/svelte';
  import * as Command from '$lib/components/ui/command/index.js';
  import * as Popover from '$lib/components/ui/popover/index.js';
  import { Button } from '$lib/components/ui/button/index.js';
  import type { KnowledgeCategory } from '$lib/api/knowledge';

  let {
    options,
    value = $bindable(''),
    placeholder = 'None',
    searchPlaceholder = 'Search or create…',
    emptyLabel = 'No matches',
    disabled = false,
    creating = false,
    allowClear = true,
    class: className = '',
    onCreate,
    onSelect
  }: {
    options: KnowledgeCategory[];
    value?: string;
    placeholder?: string;
    searchPlaceholder?: string;
    emptyLabel?: string;
    disabled?: boolean;
    creating?: boolean;
    allowClear?: boolean;
    class?: string;
    onCreate: (name: string) => Promise<KnowledgeCategory | void>;
    onSelect?: (id: string) => void;
  } = $props();

  let open = $state(false);
  let search = $state('');
  let triggerRef = $state<HTMLButtonElement | null>(null);

  const selected = $derived(options.find((option) => String(option.id) === value) ?? null);
  const trimmedSearch = $derived(search.trim());
  const exactMatch = $derived(
    trimmedSearch
      ? options.some(
          (option) => option.name.localeCompare(trimmedSearch, undefined, { sensitivity: 'accent' }) === 0
        )
      : false
  );
  const showCreate = $derived(trimmedSearch.length > 0 && !exactMatch);

  function closeAndFocusTrigger() {
    open = false;
    search = '';
    void tick().then(() => {
      triggerRef?.focus();
    });
  }

  function selectId(id: number | null) {
    const nextValue = id === null ? '' : String(id);
    value = nextValue;
    onSelect?.(nextValue);
    closeAndFocusTrigger();
  }

  async function handleCreate() {
    if (!trimmedSearch || creating) return;
    const created = await onCreate(trimmedSearch);
    if (created) {
      selectId(created.id);
    }
  }

  $effect(() => {
    if (!open) {
      search = '';
    }
  });
</script>

<Popover.Root bind:open>
  <Popover.Trigger bind:ref={triggerRef} {disabled}>
    {#snippet child({ props })}
      <Button
        {...props}
        variant="outline"
        size="lg"
        class={`h-9 w-[180px] justify-between font-normal font-sans shadow-xs ${className}`}
        role="combobox"
        aria-expanded={open}
        disabled={disabled || creating}
      >
        <span class="truncate">{selected?.name ?? placeholder}</span>
        {#if creating}
          <LoaderCircle size={16} class="shrink-0 animate-spin opacity-60" />
        {:else}
          <ChevronsUpDown size={16} class="shrink-0 opacity-50" />
        {/if}
      </Button>
    {/snippet}
  </Popover.Trigger>
  <Popover.Content class="w-[220px] p-0" align="start">
    <Command.Root shouldFilter={true}>
      <Command.Input bind:value={search} placeholder={searchPlaceholder} />
      <Command.List>
        {#if allowClear}
          <Command.Group>
            <Command.Item value="__none__" onSelect={() => selectId(null)}>None</Command.Item>
          </Command.Group>
        {/if}
        <Command.Group heading={options.length ? 'Existing' : undefined}>
          {#each options as option (option.id)}
            <Command.Item value={option.name} onSelect={() => selectId(option.id)}>
              {option.name}
            </Command.Item>
          {/each}
        </Command.Group>
        <Command.Empty>{emptyLabel}</Command.Empty>
        {#if showCreate}
          <Command.Group>
            <Command.Item
              value={`__create__ ${trimmedSearch}`}
              disabled={creating}
              onSelect={() => void handleCreate()}
            >
              {#if creating}
                <LoaderCircle size={14} class="animate-spin" />
              {:else}
                <Plus size={14} />
              {/if}
              Create "{trimmedSearch}"
            </Command.Item>
          </Command.Group>
        {/if}
      </Command.List>
    </Command.Root>
  </Popover.Content>
</Popover.Root>
