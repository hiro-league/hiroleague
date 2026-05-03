<script lang="ts">
  import { Edit3, UserRound } from '@lucide/svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import type { CharacterRow } from '$lib/api/characters';
  import { cn } from '$lib/utils';

  let {
    row,
    onEdit
  }: {
    row: CharacterRow;
    onEdit: (row: CharacterRow) => void;
  } = $props();
</script>

<article
  class="grid min-h-32 grid-cols-[64px_minmax(0,1fr)_auto] items-start gap-3 rounded-lg border bg-background/45 p-4 text-left shadow-sm"
>
  {#if row.photo_data_url}
    <img
      class="size-16 rounded-md border object-cover"
      src={row.photo_data_url}
      alt=""
      aria-hidden="true"
    />
  {:else}
    <span
      class="grid size-16 place-items-center rounded-md border border-dashed bg-muted text-muted-foreground"
    >
      <UserRound size={24} />
    </span>
  {/if}
  <span class="min-w-0 space-y-1">
    <span class="flex items-center gap-2">
      <strong class="truncate font-sans text-sm">{row.name || row.id}</strong>
      {#if row.is_default}
        <Badge variant="outline">default</Badge>
      {/if}
    </span>
    <small class="block truncate text-xs text-muted-foreground">{row.id}</small>
    <span class={cn('block text-sm', row.error ? 'text-destructive' : 'text-muted-foreground')}>
      {row.error || row.description || '-'}
    </span>
  </span>
  <Button
    variant="outline"
    size="icon"
    class="shrink-0"
    aria-label={`Edit character ${row.name || row.id}`}
    onclick={() => onEdit(row)}
  >
    <Edit3 size={17} aria-hidden="true" />
  </Button>
</article>
