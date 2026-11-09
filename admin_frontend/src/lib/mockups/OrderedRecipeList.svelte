<script lang="ts">
  /**
   * Characters (Phase 7b MOCKUP): a character's models become an ordered list of AI profiles (the
   * first that can answer asks), and its voice models + per-provider voice + style hint become an
   * ordered list of voice recipes. Replaces the model picker + tuning preset; nothing is saved.
   */
  import { ArrowDown, ArrowUp, ExternalLink, Plus, X } from '@lucide/svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import { ADMIN_SELECT } from '$lib/styling/admin-tokens';
  import { cn } from '$lib/utils';
  import {
    MOCK_DEFAULT_PROFILES,
    MOCK_VOICE_RECIPES,
    mockProfile,
    mockRecipe,
    profileLine,
    recipeLine
  } from './phase7b';

  let { voice = false }: { voice?: boolean } = $props();

  const all = $derived(voice ? MOCK_VOICE_RECIPES.map((r) => ({ id: r.id, name: r.name })) : MOCK_DEFAULT_PROFILES.map((p) => ({ id: p.id, name: p.name })));
  let ids = $state<string[]>(voice ? ['v-hiro', 'v-door'] : ['job-chat', 'job-chat-claude']);
  let adding = $state('');
  const line = (id: string) => {
    if (voice) {
      const r = mockRecipe(id);
      return r ? recipeLine(r) : '';
    }
    const p = mockProfile(id);
    return p ? profileLine(p) : '';
  };
  const name = (id: string) => all.find((x) => x.id === id)?.name ?? id;
  const move = (i: number, d: -1 | 1) => {
    const j = i + d;
    if (j < 0 || j >= ids.length) return;
    const next = [...ids];
    [next[i], next[j]] = [next[j], next[i]];
    ids = next;
  };
</script>

<div class="grid gap-2">
  <p class="flex flex-wrap items-center gap-2 font-sans text-xs">
    <Badge variant="outline" class="border-amber-500/60 text-amber-700 dark:text-amber-300">Mockup</Badge>
    <span class="text-muted-foreground">
      {voice
        ? 'Was: a list of voice models, a voice per provider and a style hint. Now: voice recipes, in order.'
        : 'Was: a list of models plus a tuning preset. Now: AI profiles, in order; the first that can answer asks.'}
    </span>
  </p>
  <ol class="grid gap-1.5">
    {#each ids as id, i (id)}
      <li class="flex items-center gap-3 rounded-md border bg-card px-3 py-2">
        <span class="w-5 shrink-0 text-center font-mono text-xs text-muted-foreground">{i + 1}</span>
        <span class="grid min-w-0 flex-1 gap-0.5">
          <span class="font-sans text-sm font-semibold">{name(id)}</span>
          <span class="truncate text-xs text-muted-foreground">{line(id)}</span>
        </span>
        <Button size="icon" variant="ghost" class="size-7" disabled={i === 0} onclick={() => move(i, -1)} aria-label="Up"><ArrowUp size={14} /></Button>
        <Button size="icon" variant="ghost" class="size-7" disabled={i === ids.length - 1} onclick={() => move(i, 1)} aria-label="Down"><ArrowDown size={14} /></Button>
        <Button size="icon" variant="ghost" class="size-7" onclick={() => (ids = ids.filter((x) => x !== id))} aria-label="Remove"><X size={14} /></Button>
      </li>
    {:else}
      <li class="rounded-md border border-dashed px-3 py-2 text-sm text-muted-foreground">
        {voice ? "None: speaks with Hiro's voice." : "None: asks with Hiro's chat profile."}
      </li>
    {/each}
  </ol>
  <div class="flex flex-wrap items-center gap-2">
    <select class={cn(ADMIN_SELECT, 'w-64')} bind:value={adding}>
      <option value="">{voice ? 'Add a voice…' : 'Add an AI profile…'}</option>
      {#each all.filter((x) => !ids.includes(x.id)) as x (x.id)}<option value={x.id}>{x.name}</option>{/each}
    </select>
    <Button
      size="sm"
      variant="outline"
      disabled={!adding}
      onclick={() => {
        ids = [...ids, adding];
        adding = '';
      }}><Plus size={13} /> Add</Button
    >
    <a class="inline-flex items-center gap-1 font-sans text-xs text-primary hover:underline" href={voice ? '/catalog/?tab=voices' : '/catalog/?tab=profiles'}
      >{voice ? 'Edit voices' : 'Edit AI profiles'} <ExternalLink size={11} /></a
    >
  </div>
</div>
