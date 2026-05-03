<script lang="ts">
  import { Save, Trash2 } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import type { CharacterDetail } from '$lib/api/characters';

  let {
    title,
    characterId,
    editCharacterDisplayLine,
    selected,
    dirty,
    busy,
    onDeleteClick,
    onCancel,
    onSave
  }: {
    title: string;
    characterId: string | null | undefined;
    editCharacterDisplayLine: string;
    selected: CharacterDetail | null;
    dirty: boolean;
    busy: boolean;
    onDeleteClick: () => void;
    onCancel: () => void;
    onSave: () => void;
  } = $props();
</script>

<div
  class="character-edit-toolbar sticky top-16 z-10 flex flex-col gap-2 border-b border-border bg-card px-4 py-3 shadow-sm backdrop-blur-md supports-[backdrop-filter]:bg-card/95 md:flex-row md:items-start md:justify-between md:gap-3 md:px-5"
>
  <div class="min-w-0 flex-1">
    <h3 class="text-2xl font-semibold">
      {title}
    </h3>
    {#if characterId}
      <p class="mt-1 flex flex-wrap items-baseline gap-x-2 gap-y-0 font-sans text-sm text-muted-foreground">
        <span class="font-semibold text-foreground">{editCharacterDisplayLine}</span>
        <span class="font-mono text-xs tracking-tight text-muted-foreground"
          >{'{'}{characterId}{'}'}</span
        >
      </p>
    {/if}
  </div>
  <div class="flex shrink-0 flex-wrap items-center gap-2 md:pt-1">
    {#if characterId && !selected?.is_default}
      <Button variant="destructive" disabled={busy} onclick={onDeleteClick}>
        <Trash2 size={15} /> Delete
      </Button>
    {/if}
    {#if dirty}
      <Button variant="outline" disabled={busy} onclick={onCancel}>Cancel</Button>
      <Button disabled={busy} onclick={onSave}><Save size={15} /> Save</Button>
    {/if}
  </div>
</div>
