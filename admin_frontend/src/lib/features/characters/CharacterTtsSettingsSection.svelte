<script lang="ts">
  import TtsVoicePresetPicker from '$lib/features/characters/TtsVoicePresetPicker.svelte';
  import CharacterSectionCard from '$lib/features/characters/CharacterSectionCard.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import type { CatalogProviderRow } from '$lib/api/catalog';
  import type { CharacterForm } from '$lib/features/characters/utils';

  let {
    form,
    catalogTtsProviders,
    google,
    openai,
    others,
    onPickVoicePreset,
    markDirty
  }: {
    form: CharacterForm;
    catalogTtsProviders: CatalogProviderRow[];
    google: CatalogProviderRow | null;
    openai: CatalogProviderRow | null;
    others: CatalogProviderRow[];
    onPickVoicePreset: (providerId: string, voiceId: string) => void;
    markDirty: () => void;
  } = $props();
</script>

<CharacterSectionCard title="TTS voice settings">
  {#if catalogTtsProviders.length > 0}
    <div class="mb-5 rounded-lg border border-border/70 bg-muted/25 p-4">
      <p class="mb-3 max-w-4xl text-sm leading-[1.45] text-muted-foreground">
        Bundled vendor voices (catalog). Google and OpenAI side‑by‑side; other providers stack under Google.
        Applies when that vendor&apos;s TTS model is chosen.
      </p>
      <div class="grid gap-4 md:grid-cols-2 md:items-start">
        <div class="grid gap-4">
          {#if google}
            <TtsVoicePresetPicker
              provider={google}
              selectedVoiceId={form.tts_voice_by_provider[google.id] ?? ''}
              onPick={onPickVoicePreset}
            />
          {/if}
          {#each others as provider (provider.id)}
            <TtsVoicePresetPicker
              {provider}
              selectedVoiceId={form.tts_voice_by_provider[provider.id] ?? ''}
              onPick={onPickVoicePreset}
            />
          {/each}
        </div>
        <div class="grid gap-4">
          {#if openai}
            <TtsVoicePresetPicker
              provider={openai}
              selectedVoiceId={form.tts_voice_by_provider[openai.id] ?? ''}
              onPick={onPickVoicePreset}
            />
          {/if}
        </div>
      </div>
    </div>
  {/if}
  <FormField label="TTS instructions (optional)">
    {#snippet children()}
      <textarea
        class="min-h-20"
        placeholder="Global style hint for speech synthesis for this character…"
        bind:value={form.tts_instructions}
        oninput={markDirty}
      ></textarea>
    {/snippet}
  </FormField>
</CharacterSectionCard>
