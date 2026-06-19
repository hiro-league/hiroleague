<script lang="ts">
  import { RefreshCw } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import InlineEmptyState from '$lib/ui/InlineEmptyState.svelte';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';
  import type { CharacterRow } from '$lib/api/characters';
  import CharacterBrowseCard from '$lib/features/characters/browse/CharacterBrowseCard.svelte';

  let {
    rows,
    loadingList,
    listError,
    onRefresh,
    onEditCharacter
  }: {
    rows: CharacterRow[];
    loadingList: boolean;
    listError: string | null;
    onRefresh: () => void;
    onEditCharacter: (row: CharacterRow) => void;
  } = $props();
</script>

<section class="grid gap-4 rounded-lg border bg-card p-5 shadow-sm">
  <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
    <div>
      <h3 class="text-lg font-semibold">Browse</h3>
      <span class="font-sans text-sm text-muted-foreground">{rows.length} characters</span>
    </div>
    <Button variant="outline" onclick={onRefresh}><RefreshCw size={15} /> Refresh</Button>
  </div>

  {#if loadingList}
    <InlineLoading label="Loading characters…" />
  {:else if listError}
    <InlineDestructiveAlert title="Could not load characters" message={listError} />
  {:else if rows.length === 0}
    <InlineEmptyState message="No characters yet. Create one with the button above." />
  {:else}
    <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
      {#each rows as row (row.id)}
        <CharacterBrowseCard {row} onEdit={onEditCharacter} />
      {/each}
    </div>
  {/if}
</section>
