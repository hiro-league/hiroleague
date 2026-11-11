<script lang="ts">
  /**
   * A character's AI profiles or voice profiles, in order (Phase 7b step 5) — replaced the preferred
   * LLM / TTS model pickers, the tuning profile select and the TTS voice settings. The lists are saved
   * as `ai_profiles_json` / `voice_profiles_json`; the saved character's resolution shows below.
   */
  import { RefreshCw } from '@lucide/svelte';
  import { Button } from '$kit/components/ui/button/index.js';
  import CharacterResolvedBlock from '$lib/features/characters/sections/CharacterResolvedBlock.svelte';
  import CharacterSectionCard from '$lib/features/characters/sections/CharacterSectionCard.svelte';
  import OrderedProfileList from '$lib/features/characters/sections/OrderedProfileList.svelte';
  import {
    characterSectionTitleClass,
    characterSectionHintClass
  } from '$lib/features/characters/shared/character-section-classes';
  import type { CharacterResolvedPayload } from '$lib/api/characters';
  import type { CharacterForm } from '$lib/features/characters/shared/characters-pure';
  import type { ProfileOption } from '$lib/features/characters/shared/profile-option';

  let {
    variant,
    form,
    characterId = undefined,
    options,
    busy,
    resolved = null,
    resolvedError = null,
    dirty = false,
    onReloadProfiles
  }: {
    variant: 'ai' | 'voice';
    form: CharacterForm;
    characterId?: string | null | undefined;
    options: ProfileOption[];
    busy: boolean;
    resolved?: CharacterResolvedPayload | null;
    resolvedError?: string | null;
    dirty?: boolean;
    onReloadProfiles: () => void;
  } = $props();

  const isAi = $derived(variant === 'ai');

  function setIds(next: string[]) {
    if (isAi) form.ai_profiles = next;
    else form.voice_profiles = next;
  }
</script>

<CharacterSectionCard>
  {#snippet header()}
    <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div class="min-w-0 flex-1">
        {#if isAi}
          <h4 class={characterSectionTitleClass}>AI profiles</h4>
          <p class={characterSectionHintClass}>
            The AI profiles this character asks with, in order: the first that can answer asks (each with its
            own fallbacks). None: Hiro's chat profile.
          </p>
        {:else}
          <h4 class={characterSectionTitleClass}>Voice profiles</h4>
          <p class={characterSectionHintClass}>
            The voice profiles this character speaks with, in order: the first whose provider has a key speaks.
            None: Hiro's voice.
          </p>
        {/if}
      </div>
      <Button
        variant="outline"
        size="sm"
        class="shrink-0"
        disabled={busy}
        title="Read the profiles again (after editing them in Catalog → Profiles)"
        onclick={onReloadProfiles}
      >
        <RefreshCw size={14} /> Reload profiles
      </Button>
    </div>
  {/snippet}

  <OrderedProfileList
    kind={variant}
    ids={isAi ? form.ai_profiles : form.voice_profiles}
    {options}
    disabled={busy}
    onchange={setIds}
  />

  {#if characterId}
    <div class="mt-6">
      <CharacterResolvedBlock
        {resolved}
        error={resolvedError}
        staleHint={dirty}
        segment={isAi ? 'llm' : 'voice'}
      />
    </div>
  {/if}
</CharacterSectionCard>
