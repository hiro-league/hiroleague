<script lang="ts">
  import { ArrowUpRight } from '@lucide/svelte';
  import type { CatalogProviderRow, CatalogTtsVoiceRow } from '$lib/api/catalog';
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

  /** Display label (catalog ``display_name`` or API ``id``) vs optional description — styled separately in the UI. */
  function voicePresetParts(v: CatalogTtsVoiceRow): { name: string; desc: string | null } {
    return {
      name: v.display_name?.trim() || v.id,
      desc: v.description?.trim() || null
    };
  }

  const isDefaultVoice = $derived(!selectedVoiceId.trim());

  const selectedVoiceDisplay = $derived.by((): { name: string; desc: string | null } | null => {
    if (!selectedVoiceId.trim()) return null;
    const row = provider.tts_voices?.find((v) => v.id === selectedVoiceId);
    if (!row) return { name: selectedVoiceId, desc: null };
    return voicePresetParts(row);
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
    <span class="inline-flex flex-wrap items-baseline gap-x-0 font-normal">
      <span class="text-muted-foreground">·&nbsp;</span>
      {#if isDefaultVoice}
        <span class="text-muted-foreground">Catalog default</span>
      {:else if selectedVoiceDisplay}
        <span class="font-medium text-foreground">{selectedVoiceDisplay.name}</span>
        {#if selectedVoiceDisplay.desc}
          <span class="text-muted-foreground"> · {selectedVoiceDisplay.desc}</span>
        {/if}
      {/if}
    </span>
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
      {@const parts = voicePresetParts(v)}
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
        <span class="min-w-0 leading-snug">
          <span class="font-medium text-foreground">{parts.name}</span>
          {#if parts.desc}
            <span class="text-muted-foreground"> · {parts.desc}</span>
          {/if}
        </span>
      </button>
    {/each}
  </div>
</div>
