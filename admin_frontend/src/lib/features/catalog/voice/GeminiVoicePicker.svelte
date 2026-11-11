<script lang="ts">
  /**
   * Picks a Gemini voice for a voice profile (Phase 7b), as HomeHiro's TTS page did, from three places
   * (Gemini's own voice list, read by the core and cached a day):
   *  - Studio: Gemini's 30 voices in a dropdown; the one picked is described under it, with a sample.
   *  - Voice library: about 2,000 voices, filtered by language (with counts) and gender and searched as
   *    you type; the first 60 matches are listed.
   *  - My voices: the voices designed on this account, with how long Google keeps each, and everything
   *    about them here (no page of their own): Delete at Google (asked on the row), Design a voice
   *    (who is speaking, name, language, gender; the profile uses the new voice at once), add one made in
   *    AI Studio, Reload.
   * Each row: name and detail, a sample to hear (one plays at a time; the core makes and keeps it), Use / Used.
   */
  import { onDestroy } from 'svelte';
  import { Check, Loader, Play, Plus, RefreshCw, Square, Trash2, Wand, X } from '@lucide/svelte';
  import { Badge } from '$kit/components/ui/badge/index.js';
  import { Button } from '$kit/components/ui/button/index.js';
  import Notice from '$kit/ui/notice.svelte';
  import {
    addVoice,
    deleteVoice,
    designVoice,
    listVoices,
    voiceClipUrl,
    voiceSampleUrl,
    type GeminiVoice,
    type VoiceSource
  } from '$lib/api/voice';
  import { ADMIN_INPUT, ADMIN_SELECT } from '$lib/styling/admin-tokens';
  import { cn } from '$lib/utils';
  import { keptUntil, langName, sourceOf } from './voice-format';

  let {
    value,
    designLanguages,
    onpick
  }: {
    value: string;
    designLanguages: string[];
    onpick: (v: { id: string; label: string; source: VoiceSource }) => void;
  } = $props();

  const same = (a: string, b: string) => a.toLowerCase() === b.toLowerCase();
  // svelte-ignore state_referenced_locally
  let tab = $state<VoiceSource>(sourceOf(value)); // opens on the tab the voice is from
  let error = $state<string | null>(null);

  // ── Lists ──
  let studio = $state<GeminiVoice[]>([]);
  let mine = $state<GeminiVoice[]>([]);
  let library = $state<GeminiVoice[]>([]);
  let libraryTotal = $state(0);
  let languages = $state<{ code: string; count: number }[]>([]);
  let loading = $state(false);
  let language = $state('');
  let gender = $state('');
  let query = $state('');

  async function load(source: VoiceSource, refresh = false) {
    loading = true;
    // Step 1d: a failed request throws (answers are the data itself; there is no {ok, error} to test).
    let res: Awaited<ReturnType<typeof listVoices>>;
    try {
      res =
        source === 'library'
          ? await listVoices({ source, language, gender, q: query.trim(), limit: 60, refresh })
          : await listVoices({ source, limit: 300, refresh });
    } catch (err) {
      error = err instanceof Error ? err.message : "Gemini's voices could not be read.";
      return;
    } finally {
      loading = false;
    }
    error = null;
    if (source === 'studio') studio = res.voices;
    else if (source === 'mine') mine = res.voices;
    else {
      library = res.voices;
      libraryTotal = res.total;
      languages = res.languages;
    }
  }

  // Each tab reads its voices when shown; the library again as its filters change (typing waits a moment).
  let searchTimer: ReturnType<typeof setTimeout> | undefined;
  $effect(() => {
    const t = tab;
    if (t !== 'library') {
      void load(t);
      return;
    }
    void language;
    void gender;
    void query;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => void load('library'), 250);
  });

  // ── Samples: one plays at a time ──
  let playing = $state<string | null>(null);
  let fetching = $state<string | null>(null);
  let player: HTMLAudioElement | null = null;
  function play(id: string, src: string) {
    player?.pause();
    if (playing === id) {
      playing = null;
      return;
    }
    player = new Audio(src);
    playing = fetching = id;
    player.oncanplay = () => (fetching = null);
    player.onended = () => (playing = null);
    player.onerror = () => {
      error = "That sample couldn't be played.";
      playing = fetching = null;
    };
    void player.play().catch(() => (playing = fetching = null));
  }
  onDestroy(() => player?.pause());

  // ── My voices: design, delete (asked on the row), add from AI Studio ──
  let confirmDelete = $state<string | null>(null);
  let deleting = $state(false);
  let designOpen = $state(false);
  let form = $state({ who: '', name: '', language: '', gender: '' });
  let designing = $state(false);
  let designed = $state<{ name: string; cost: number | null; clipId: string } | null>(null);
  let pasteId = $state('');
  let adding = $state(false);
  const canDesign = $derived(!!form.name.trim() && form.who.trim().length >= 10 && !designing);

  async function design() {
    designing = true;
    let res: Awaited<ReturnType<typeof designVoice>>;
    try {
      res = await designVoice({
        name: form.name.trim(),
        description: form.who.trim(),
        language: form.language || undefined,
        gender: form.gender || undefined
      });
    } catch (err) {
      error = err instanceof Error ? err.message : 'The voice was not designed.';
      return;
    } finally {
      designing = false;
    }
    error = null;
    designed = { name: res.voice.name, cost: res.clip.cost_usd, clipId: res.clip.id };
    pick(res.voice); // as in HomeHiro: the new voice is used by this profile at once
    form.who = form.name = '';
    await load('mine');
  }
  async function remove(v: GeminiVoice) {
    deleting = true;
    try {
      await deleteVoice(v.id);
    } catch (err) {
      error = err instanceof Error ? err.message : 'The voice was not deleted.';
      return;
    } finally {
      deleting = false;
      confirmDelete = null;
    }
    error = null;
    await load('mine');
  }
  async function add() {
    adding = true;
    try {
      await addVoice(pasteId.trim());
    } catch (err) {
      error = err instanceof Error ? err.message : 'The voice was not added.';
      return;
    } finally {
      adding = false;
    }
    error = null;
    pasteId = '';
    await load('mine', true);
  }

  const chosen = (v: GeminiVoice) => same(value, v.id);
  const pick = (v: GeminiVoice) => onpick({ id: v.id, label: v.source === 'library' ? v.id : v.name, source: v.source });
  const selectedStudio = $derived(studio.find(chosen));
  const hint = (v: GeminiVoice) => (v.description ?? '').split(',')[0];

  const TABS: { value: VoiceSource; label: string }[] = [
    { value: 'studio', label: 'Studio' },
    { value: 'library', label: 'Voice library' },
    { value: 'mine', label: 'My voices' }
  ];
  const pill = (on: boolean) =>
    cn('rounded-md px-2.5 py-1 font-sans text-xs font-medium', on ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-accent');
</script>

{#snippet sample(id: string)}
  <Button size="sm" variant="ghost" title={playing === id ? 'Stop' : 'Hear a sample'} onclick={() => play(id, voiceSampleUrl(id))}>
    {#if fetching === id}<Loader size={13} class="animate-spin" />{:else if playing === id}<Square size={13} />{:else}<Play size={13} />{/if}
  </Button>
{/snippet}

{#snippet row(v: GeminiVoice, detail: string)}
  <div class={cn('flex items-center gap-2 rounded-md px-2 py-1.5', chosen(v) && 'bg-muted')} title={v.description ?? ''}>
    <span class="grid min-w-0 flex-1">
      <span class="truncate font-sans text-sm font-medium">
        {v.name}{#if v.source === 'library'}<span class="ml-1.5 font-mono text-xs font-normal text-muted-foreground">{v.id}</span>{/if}
      </span>
      <span class="truncate text-xs text-muted-foreground">{detail}</span>
    </span>
    {@render sample(v.id)}
    {#if chosen(v)}
      <Badge variant="outline"><Check size={12} /> Used</Badge>
    {:else}
      <Button size="sm" variant="outline" onclick={() => pick(v)}>Use</Button>
    {/if}
    {#if v.source === 'mine'}
      <Button size="sm" variant="ghost" class="text-destructive" title="Delete this voice at Google" onclick={() => (confirmDelete = v.id)}><Trash2 size={13} /></Button>
    {/if}
  </div>
  {#if confirmDelete === v.id}
    <!-- Asked here, on the row: no second dialog over the editor. -->
    <div class="flex flex-wrap items-center gap-2 rounded-md border border-destructive/40 px-2 py-1.5 text-xs">
      <span class="flex-1">Delete "{v.name}" at Google? This cannot be undone. A voice profile still using it is refused.</span>
      <Button size="sm" variant="destructive" disabled={deleting} onclick={() => remove(v)}>Delete</Button>
      <Button size="sm" variant="ghost" onclick={() => (confirmDelete = null)}>Cancel</Button>
    </div>
  {/if}
{/snippet}

<div class="grid gap-3 rounded-md border bg-background p-3">
  <span class="inline-flex w-fit gap-1 rounded-lg border bg-card p-1" role="group" aria-label="Where the voice is from">
    {#each TABS as t (t.value)}
      <button type="button" class={pill(tab === t.value)} onclick={() => (tab = t.value)}>{t.label}</button>
    {/each}
  </span>

  {#if error}<Notice message={error} />{/if}

  {#if tab === 'studio'}
    <select
      class={cn(ADMIN_SELECT, 'sm:w-2/3')}
      value={selectedStudio?.id ?? ''}
      onchange={(e) => {
        const v = studio.find((x) => x.id === e.currentTarget.value);
        if (v) pick(v);
      }}
    >
      {#if !selectedStudio}<option value="" disabled>{loading ? 'Reading the voices…' : `Pick one of ${studio.length} studio voices`}</option>{/if}
      {#each studio as v (v.id)}<option value={v.id}>{v.name} · {hint(v)}{v.gender ? ` · ${v.gender}` : ''}</option>{/each}
    </select>
    {#if selectedStudio}
      <div class="flex items-center gap-2">
        <p class="flex-1 text-xs text-muted-foreground">{selectedStudio.description}</p>
        {@render sample(selectedStudio.id)}
      </div>
    {/if}
  {:else if tab === 'library'}
    <div class="grid gap-2 sm:grid-cols-[1fr_8rem_1fr]">
      <select class={ADMIN_SELECT} bind:value={language}>
        <option value="">Any language</option>
        {#each languages as l (l.code)}<option value={l.code}>{langName(l.code)} ({l.count})</option>{/each}
      </select>
      <select class={ADMIN_SELECT} bind:value={gender}>
        <option value="">Any gender</option><option value="female">female</option><option value="male">male</option>
      </select>
      <input class={ADMIN_INPUT} bind:value={query} placeholder="Search: warm, narrator, Egyptian…" />
    </div>
    <div class="grid max-h-72 gap-0.5 overflow-y-auto">
      {#each library as v (v.id)}
        {@render row(v, [v.language ? langName(v.language) : '', v.accent, v.gender, v.persona].filter(Boolean).join(' · '))}
      {:else}
        <p class="px-2 py-1.5 text-sm text-muted-foreground">{loading ? 'Reading the voices…' : 'No voices match.'}</p>
      {/each}
    </div>
    <p class="text-xs text-muted-foreground">
      Showing {library.length} of {libraryTotal.toLocaleString('en-US')}.{libraryTotal > library.length ? ' Narrow the search to see others.' : ''}
    </p>
  {:else}
    <div class="grid gap-0.5">
      {#each mine as v (v.id)}
        {@render row(v, [v.description, keptUntil(v.expires)].filter(Boolean).join(' · '))}
      {:else}
        <p class="px-2 py-1.5 text-sm text-muted-foreground">{loading ? 'Reading the voices…' : 'No voices of your own yet.'}</p>
      {/each}
    </div>

    {#if designOpen}
      <!-- Inline, under the list (as in HomeHiro): no page of its own, no dialog. -->
      <div class="grid gap-3 rounded-md bg-muted/50 p-3">
        <div class="flex items-center justify-between">
          <span class="font-sans text-sm font-semibold">Design a voice</span>
          <Button size="sm" variant="ghost" onclick={() => (designOpen = false)} aria-label="Close"><X size={14} /></Button>
        </div>
        <label class="grid gap-1 text-xs text-muted-foreground">
          <span class="font-sans text-sm font-medium text-foreground">Who is speaking</span>
          <textarea rows="2" bind:value={form.who} placeholder="e.g. A man in his 40s with a light Lebanese accent, a deep and gentle voice."></textarea>
          Age, gender, accent, what the voice sounds like. Used once, to make the voice; how it speaks (tone, pace) is this profile's speaking style.
        </label>
        <div class="grid gap-2 sm:grid-cols-3">
          <input class={ADMIN_INPUT} bind:value={form.name} placeholder="Name, e.g. Hiro" maxlength="80" />
          <select class={ADMIN_SELECT} bind:value={form.language}>
            <option value="">Any language</option>
            {#each designLanguages as l (l)}<option value={l}>{langName(l)}</option>{/each}
          </select>
          <select class={ADMIN_SELECT} bind:value={form.gender}><option value="">Any gender</option><option value="female">female</option><option value="male">male</option></select>
        </div>
        <div class="flex flex-wrap items-center gap-3">
          <Button onclick={design} disabled={!canDesign}>
            {#if designing}<Loader size={14} class="animate-spin" /> Designing… (about 30 s){:else}<Wand size={14} /> Design and preview{/if}
          </Button>
          <span class="text-xs text-muted-foreground">Gemini 3.8 Flash TTS makes it (about 2¢) and Google keeps it for a year, up to 200 voices.</span>
        </div>
        {#if designed}
          <div class="grid gap-1">
            <span class="text-xs text-muted-foreground"
              >Made <span class="font-medium text-foreground">{designed.name}</span>{designed.cost !== null ? ` for $${designed.cost.toFixed(4)}` : ''}, and this
              profile uses it now:</span
            >
            <audio controls class="h-9 w-full" src={voiceClipUrl(designed.clipId)}></audio>
          </div>
        {/if}
      </div>
    {/if}

    <div class="flex flex-wrap items-center gap-2">
      {#if !designOpen}<Button size="sm" variant="outline" onclick={() => (designOpen = true)}><Plus size={13} /> Design a voice</Button>{/if}
      <input class={cn(ADMIN_INPUT, 'h-8 min-w-48 flex-1')} bind:value={pasteId} placeholder="Or add one made in AI Studio: voice_abc123" />
      <Button size="sm" variant="outline" disabled={!pasteId.trim().startsWith('voice_') || adding} onclick={add}>Add</Button>
      <Button size="sm" variant="ghost" title="Reload from Google" disabled={loading} onclick={() => load('mine', true)}><RefreshCw size={13} /></Button>
    </div>
  {/if}
</div>
