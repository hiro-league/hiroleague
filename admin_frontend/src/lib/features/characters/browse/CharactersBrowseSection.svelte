<script lang="ts">
  import ResourceView from '$kit/ui/resource-view.svelte';
  import Panel from '$kit/ui/panel.svelte';
  import { RefreshCw } from '@lucide/svelte';
  import { Button } from '$kit/components/ui/button/index.js';
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

  const view = $derived({
    data: rows.length || !(loadingList || listError) ? rows : null,
    error: listError ?? '',
    loading: loadingList,
    reload: () => onRefresh()
  });
</script>

<Panel title="Browse" description={`${rows.length} characters`}>
  {#snippet actions()}
    <Button variant="outline" onclick={onRefresh}><RefreshCw size={15} /> Refresh</Button>
  {/snippet}
  <ResourceView
    resource={view}
    loadingLabel="Loading characters…"
    errorTitle="Could not load characters"
    empty={(d) => d.length === 0}
    emptyMessage="No characters yet. Create one with the button above."
    quiet
  >
    {#snippet children()}
      <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {#each rows as row (row.id)}
          <CharacterBrowseCard {row} onEdit={onEditCharacter} />
        {/each}
      </div>
    {/snippet}
  </ResourceView>
</Panel>
