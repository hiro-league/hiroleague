<script lang="ts">
  /**
   * A character's ordered list of profiles (Phase 7b step 5): AI profiles (the first that can answer
   * asks) or voice profiles (the first whose provider has a key speaks). Up / down / remove per row, an
   * "Add" select of the profiles not in the list yet, and a link to edit them in Catalog → Profiles.
   * Empty means Hiro's own: its chat profile / its voice. Replaced the catalog model pickers.
   */
  import { ArrowDown, ArrowUp, ExternalLink, Plus, X } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { ADMIN_SELECT } from '$lib/styling/admin-tokens';
  import { cn } from '$lib/utils';
  import { moveInList } from '$lib/features/characters/shared/characters-pure';
  import type { ProfileOption } from '$lib/features/characters/shared/profile-option';

  let {
    kind,
    ids,
    options,
    disabled = false,
    onchange
  }: {
    kind: 'ai' | 'voice';
    ids: string[];
    options: ProfileOption[];
    disabled?: boolean;
    onchange: (next: string[]) => void;
  } = $props();

  let adding = $state('');
  const byId = $derived(new Map(options.map((o) => [o.id, o])));
  const addable = $derived(options.filter((o) => !ids.includes(o.id)));
  const noun = $derived(kind === 'ai' ? 'AI profile' : 'voice profile');

  function add() {
    if (!adding || ids.includes(adding)) return;
    onchange([...ids, adding]);
    adding = '';
  }
</script>

<div class="grid gap-2">
  <ol class="grid gap-1.5" aria-label={kind === 'ai' ? 'AI profiles, in order' : 'Voice profiles, in order'}>
    {#each ids as id, i (id)}
      {@const option = byId.get(id)}
      <li class="flex items-center gap-3 rounded-md border bg-card px-3 py-2">
        <span class="w-5 shrink-0 text-center font-mono text-xs text-muted-foreground">{i + 1}</span>
        <span class="grid min-w-0 flex-1 gap-0.5">
          <span class="font-sans text-sm font-semibold">{option?.label ?? id}</span>
          {#if option}
            <span class="truncate text-xs text-muted-foreground" title={option.line}>{option.line}</span>
            {#if option.note}<span class="text-xs text-amber-700 dark:text-amber-300">{option.note}</span>{/if}
          {:else}
            <!-- Deleted in Catalog → Profiles since: skipped when it's this one's turn; remove it here. -->
            <span class="text-xs text-amber-700 dark:text-amber-300">No {noun} "{id}" any more: it is skipped.</span>
          {/if}
        </span>
        <Button
          size="icon"
          variant="ghost"
          class="size-7"
          disabled={disabled || i === 0}
          onclick={() => onchange(moveInList(ids, i, -1))}
          aria-label={`Move ${option?.label ?? id} up`}><ArrowUp size={14} /></Button
        >
        <Button
          size="icon"
          variant="ghost"
          class="size-7"
          disabled={disabled || i === ids.length - 1}
          onclick={() => onchange(moveInList(ids, i, 1))}
          aria-label={`Move ${option?.label ?? id} down`}><ArrowDown size={14} /></Button
        >
        <Button
          size="icon"
          variant="ghost"
          class="size-7"
          {disabled}
          onclick={() => onchange(ids.filter((x) => x !== id))}
          aria-label={`Remove ${option?.label ?? id}`}><X size={14} /></Button
        >
      </li>
    {:else}
      <li class="rounded-md border border-dashed px-3 py-2 text-sm text-muted-foreground">
        {kind === 'ai' ? "None: asks with Hiro's chat profile." : "None: speaks with Hiro's voice."}
      </li>
    {/each}
  </ol>
  <div class="flex flex-wrap items-center gap-2">
    <select
      class={cn(ADMIN_SELECT, 'w-64')}
      aria-label={`Add ${noun}`}
      bind:value={adding}
      disabled={disabled || addable.length === 0}
    >
      <option value="">{addable.length ? `Add ${kind === 'ai' ? 'an' : 'a'} ${noun}…` : `No other ${noun}s`}</option>
      {#each addable as option (option.id)}<option value={option.id}>{option.label}</option>{/each}
    </select>
    <Button size="sm" variant="outline" disabled={disabled || !adding} onclick={add}><Plus size={13} /> Add</Button>
    <a
      class="inline-flex items-center gap-1 font-sans text-xs text-primary hover:underline"
      href={kind === 'ai' ? '/catalog/?tab=profiles' : '/catalog/?tab=voices'}
      >Edit in Catalog → Profiles <ExternalLink size={11} aria-hidden="true" /></a
    >
  </div>
</div>
