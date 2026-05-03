<script lang="ts">
  import { ArrowLeft, Edit3, UserRound } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import MarkdownPreview from '$lib/components/ui/markdown/MarkdownPreview.svelte';
  import CharacterResolvedBlock from '$lib/features/characters/CharacterResolvedBlock.svelte';
  import { prettyJson } from '$lib/features/characters/utils';
  import type { CharacterDetail, CharacterResolvedPayload } from '$lib/api/characters';

  let {
    loadingDetail,
    detailError,
    selected,
    resolved,
    resolvedError,
    onOpenBrowse,
    onEnterEdit
  }: {
    loadingDetail: boolean;
    detailError: string | null;
    selected: CharacterDetail | null;
    resolved: CharacterResolvedPayload | null;
    resolvedError: string | null;
    onOpenBrowse: () => void;
    onEnterEdit: () => void;
  } = $props();
</script>

<section class="grid gap-5 rounded-lg border bg-card p-5 shadow-sm">
  {#if loadingDetail}
    <p class="text-muted-foreground">Loading character...</p>
  {:else if detailError}
    <div class="rounded-md border border-destructive/30 bg-destructive/10 p-3 text-destructive">
      <strong class="font-sans">Could not load character</strong>
      <span class="block text-sm">{detailError}</span>
    </div>
  {:else if !selected}
    <div class="grid gap-3">
      <h3 class="text-lg font-semibold">No character selected</h3>
      <p class="text-sm text-muted-foreground">Pick a character from Browse or create a new one.</p>
      <div><Button onclick={onOpenBrowse}><ArrowLeft size={15} /> Go to Browse</Button></div>
    </div>
  {:else}
    <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
      <h3 class="min-w-0 truncate text-2xl font-semibold">{selected.name || selected.id}</h3>
      <div class="flex flex-wrap gap-2">
        <Button onclick={onEnterEdit}><Edit3 size={15} /> Edit</Button>
        <Button variant="outline" onclick={onOpenBrowse}><ArrowLeft size={15} /> Back to Browse</Button>
      </div>
    </div>

    <div class="grid gap-6 lg:grid-cols-[208px_minmax(0,1fr)]">
      <div class="grid content-start gap-2">
        {#if selected.photo_data_url}
          <img class="size-48 rounded-md border object-cover" src={selected.photo_data_url} alt="" />
        {:else}
          <div
            class="grid size-48 place-items-center rounded-md border border-dashed bg-muted text-muted-foreground"
          >
            <UserRound size={54} />
          </div>
        {/if}
        {#if selected.photo_error}
          <p class="max-w-48 text-xs text-destructive">{selected.photo_error}</p>
        {/if}
      </div>
      <div class="grid min-w-0 gap-4">
        <div>
          <span class="font-sans text-xs font-semibold uppercase text-muted-foreground">Id</span>
          <p class="font-sans text-sm">{selected.id}</p>
        </div>
        <div>
          <span class="font-sans text-xs font-semibold uppercase text-muted-foreground">Description</span>
          <p class="text-sm">{selected.description || '-'}</p>
        </div>
        <div>
          <span class="font-sans text-xs font-semibold uppercase text-muted-foreground">Prompt</span>
          <div class="mt-1 rounded-md border bg-background/45 p-3 text-sm">
            <MarkdownPreview markdown={selected.prompt} compact />
          </div>
        </div>
        <div>
          <span class="font-sans text-xs font-semibold uppercase text-muted-foreground">Backstory</span>
          <div class="mt-1 rounded-md border bg-background/45 p-3 text-sm">
            <MarkdownPreview markdown={selected.backstory} compact />
          </div>
        </div>
        <div class="grid gap-3 md:grid-cols-2">
          <div>
            <span class="font-sans text-xs font-semibold uppercase text-muted-foreground">LLM models</span>
            <pre class="mt-1 overflow-auto rounded-md border bg-background/45 p-3 text-xs">{prettyJson(selected.llm_models) || '-'}</pre>
          </div>
          <div>
            <span class="font-sans text-xs font-semibold uppercase text-muted-foreground">Voice models</span>
            <pre class="mt-1 overflow-auto rounded-md border bg-background/45 p-3 text-xs">{prettyJson(selected.voice_models) || '-'}</pre>
          </div>
        </div>

        <CharacterResolvedBlock resolved={resolved} error={resolvedError} staleHint={false} segment="full" />
      </div>
    </div>
  {/if}
</section>
