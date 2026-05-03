<script lang="ts">
  import { ArrowUpRight } from '@lucide/svelte';
  import type { CatalogProviderRow } from '$lib/api/catalog';
  import { cn } from '$lib/utils';
  import { tick } from 'svelte';

  /** Official public pages listing prebuilt TTS voice names (admin convenience; keep in sync with vendor docs). */
  const TTS_VOICE_LIST_DOCS: Partial<Record<string, string>> = {
    google: 'https://ai.google.dev/gemini-api/docs/speech-generation#voices',
    openai: 'https://platform.openai.com/docs/guides/text-to-speech#voice-options'
  };

  /** Scroll ``el`` within ``container`` only — ``scrollIntoView`` also scrolls ancestors up to the window and jumps the page. */
  function scrollWithinContainer(container: HTMLElement, el: HTMLElement, padPx = 8) {
    const cr = container.getBoundingClientRect();
    const er = el.getBoundingClientRect();
    const topGap = er.top - cr.top;
    const bottomGap = er.bottom - cr.bottom;
    if (topGap < padPx) {
      container.scrollTop += topGap - padPx;
    } else if (bottomGap > -padPx) {
      container.scrollTop += bottomGap + padPx;
    }
  }

  let {
    provider,
    selectedVoiceId,
    onPick
  }: {
    provider: CatalogProviderRow;
    selectedVoiceId: string;
    onPick: (providerId: string, voiceId: string) => void;
  } = $props();

  let listRoot = $state<HTMLDivElement | null>(null);

  const vendorVoiceListDocsUrl = $derived(TTS_VOICE_LIST_DOCS[provider.id] ?? null);

  const selectionSummary = $derived.by(() => {
    if (!selectedVoiceId.trim()) {
      return 'Catalog default';
    }
    const row = provider.tts_voices?.find((v) => v.id === selectedVoiceId);
    const name = row?.display_name?.trim();
    return name || selectedVoiceId;
  });

  // Keep the highlighted option visible inside this listbox only (never scroll the document).
  $effect(() => {
    const id = selectedVoiceId;
    const n = provider.tts_voices?.length ?? 0;
    void id;
    void n;
    void listRoot;
    tick().then(() => {
      const root = listRoot;
      if (!root) return;
      const selected = root.querySelector<HTMLElement>('[role="option"][aria-selected="true"]');
      if (!selected) return;
      scrollWithinContainer(root, selected);
    });
  });
</script>

<div class="grid min-w-0 gap-2">
  <p class="flex flex-wrap items-baseline gap-x-1.5 gap-y-0.5 font-sans text-sm leading-snug text-foreground">
    <span class="inline-flex items-center gap-1">
      <span class="font-semibold">{provider.display_name}</span>
      {#if vendorVoiceListDocsUrl}
        <a
          href={vendorVoiceListDocsUrl}
          target="_blank"
          rel="noopener noreferrer"
          class="inline-flex shrink-0 rounded p-0.5 text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-label={`${provider.display_name} — official TTS voice list (opens in new tab)`}
          title="Official TTS voice list (new tab)"
        >
          <ArrowUpRight size={14} strokeWidth={2.25} aria-hidden="true" />
        </a>
      {/if}
    </span>
    <span class="font-normal text-muted-foreground">· {selectionSummary}</span>
  </p>
  <div
    bind:this={listRoot}
    class="tts-voice-listbox max-h-[11rem] min-h-[7rem] overflow-y-auto rounded-md border border-input bg-background"
    role="listbox"
    aria-label={`Bundled voices for ${provider.display_name}`}
  >
    <button
      type="button"
      role="option"
      aria-selected={selectedVoiceId === ''}
      class={cn(
        'flex w-full border-b border-border/60 px-3 py-2 text-left font-sans text-sm transition-colors',
        selectedVoiceId === ''
          ? 'bg-primary/15 font-medium text-foreground'
          : 'text-foreground hover:bg-accent/60'
      )}
      onclick={() => onPick(provider.id, '')}
    >
      Catalog default
    </button>
    {#each provider.tts_voices ?? [] as v (v.id)}
      <button
        type="button"
        role="option"
        aria-selected={selectedVoiceId === v.id}
        class={cn(
          'flex w-full border-b border-border/60 px-3 py-2 text-left font-sans text-sm transition-colors last:border-b-0',
          selectedVoiceId === v.id
            ? 'bg-primary/15 font-medium text-foreground'
            : 'text-foreground hover:bg-accent/60'
        )}
        onclick={() => onPick(provider.id, v.id)}
      >
        {v.display_name?.trim() ? v.display_name : v.id}
      </button>
    {/each}
  </div>
</div>
