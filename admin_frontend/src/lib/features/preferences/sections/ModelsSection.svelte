<script lang="ts">
  import PrefSectionCard from '$lib/features/preferences/widgets/PrefSectionCard.svelte';
  import PrefPanel from '$lib/features/preferences/widgets/PrefPanel.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { modalityKeys } from '$lib/features/preferences/shared/preferences-constants';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import {
    PREFERENCE_TAB_IDS,
    PREFERENCE_TAB_PANEL_IDS
  } from '$lib/features/preferences/shared/preferences-tabs';
  import PrefEmbedderDownload from '$lib/features/preferences/widgets/PrefEmbedderDownload.svelte';
  import PrefFieldGrid from '$lib/features/preferences/widgets/PrefFieldGrid.svelte';
  import PrefModelPicker from '$lib/features/preferences/widgets/PrefModelPicker.svelte';
  import PrefRerankerDownload from '$lib/features/preferences/widgets/PrefRerankerDownload.svelte';
  import PrefToggleField from '$lib/features/preferences/widgets/PrefToggleField.svelte';
  import TuningProfileSelect from '$lib/features/preferences/widgets/TuningProfileSelect.svelte';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();
</script>

<div
  id={PREFERENCE_TAB_PANEL_IDS.models}
  class="grid gap-4"
  role="tabpanel"
  aria-labelledby={PREFERENCE_TAB_IDS.models}
>
  {#if ctrl.sectionDescription('llm')}
    <p class="text-sm text-muted-foreground">{ctrl.sectionDescription('llm')}</p>
  {/if}

  {#if ctrl.draft}
    <!-- All default models live in one card so they read as a single group. -->
    <PrefSectionCard
      title="Default models"
      description="Fallback models used when a character has no available preferred model."
      collapsible
      bodyId={PREFERENCES_SECTION_BODY_IDS.modelsChat}
    >
      <!-- Each picker is its own titled cell so the 2-column grid packs (no half-empty rows);
           order places the chat profile under chat and TTS in the slot STT would otherwise leave bare. -->
      <PrefFieldGrid>
        <PrefModelPicker
          {ctrl}
          kind="chat"
          path="llm.default_chat"
          embedded
          labelled
          selectedId={ctrl.draft.llm.default_chat}
        />
        <PrefModelPicker
          {ctrl}
          kind="stt"
          path="llm.default_stt"
          embedded
          labelled
          selectedId={ctrl.draft.llm.default_stt}
        />
        <TuningProfileSelect
          {ctrl}
          path="llm.default_tuning_profile"
          value={ctrl.draft.llm.default_tuning_profile}
          scope="llm"
        />
        <PrefModelPicker
          {ctrl}
          kind="tts"
          path="llm.default_tts"
          embedded
          labelled
          selectedId={ctrl.draft.llm.default_tts}
        />
        <!-- Workspace default embedder. Never locked — the per-tool overrides (Knowledge / Graph)
             lock instead, on their own indexing. Local models get the inline download here. -->
        <div class="grid gap-2">
          <PrefModelPicker
            {ctrl}
            kind="embedding"
            path="llm.default_embedder"
            embedded
            labelled
            selectedId={ctrl.draft.llm.default_embedder}
          />
          <PrefEmbedderDownload {ctrl} modelId={ctrl.draft.llm.default_embedder} />
        </div>
        <!-- Default reranker — the shared fallback for both the knowledge and graph rerankers
             (each can still override it in its own tab). Local models get the inline download
             affordance here since this is where the default is chosen. -->
        <div class="grid gap-2">
          <PrefModelPicker
            {ctrl}
            kind="rerank"
            path="llm.default_reranker"
            embedded
            labelled
            selectedId={ctrl.draft.llm.default_reranker}
          />
          <PrefRerankerDownload {ctrl} modelId={ctrl.draft.llm.default_reranker} />
        </div>
      </PrefFieldGrid>
    </PrefSectionCard>

    <!-- Media modalities — merged in from the former standalone Media tab. The section
         description now lives inside the card instead of as a sibling paragraph. -->
    <PrefSectionCard
      title="Modalities"
      description={ctrl.sectionDescription('media')}
      collapsible
      bodyId={PREFERENCES_SECTION_BODY_IDS.mediaInput}
    >
      <div class="grid gap-4">
        <PrefPanel {ctrl} title="Input Modalities">
          <PrefFieldGrid>
            {#each modalityKeys as key (key)}
              <PrefToggleField
                {ctrl}
                path={`media.input.${key}`}
                bind:checked={ctrl.draft.media.input[key]}
              />
            {/each}
          </PrefFieldGrid>
        </PrefPanel>
        <PrefPanel {ctrl} title="Output Modalities">
          <PrefFieldGrid>
            {#each modalityKeys as key (key)}
              <PrefToggleField
                {ctrl}
                path={`media.output.${key}`}
                bind:checked={ctrl.draft.media.output[key]}
              />
            {/each}
          </PrefFieldGrid>
        </PrefPanel>
      </div>
    </PrefSectionCard>
  {/if}
</div>
