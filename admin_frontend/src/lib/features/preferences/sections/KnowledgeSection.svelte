<script lang="ts">
  import Badge from '$lib/components/ui/badge.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { knowledgeAnsweringModelHint } from '$lib/features/preferences/shared/preferences-helpers';
  import {
    ADMIN_SECTION_CARD_MUTED,
    ADMIN_SELECT_LG,
    PREFERENCE_SECTION_SCROLL_MT
  } from '$lib/features/preferences/shared/preferences-ui';
  import SingleModelPicker from '$lib/features/preferences/SingleModelPicker.svelte';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();
</script>

<section id="preferences-knowledge" class="{PREFERENCE_SECTION_SCROLL_MT} grid gap-4 border-b pb-6">
  <div>
    <h3 class="font-sans text-xl font-semibold text-foreground">
      {ctrl.sectionLabel('knowledge', 'Knowledge')}
    </h3>
    <p class="mt-1 text-sm text-muted-foreground">{ctrl.sectionDescription('knowledge')}</p>
  </div>

  {#if ctrl.draft}
    <div class="grid gap-3 {ADMIN_SECTION_CARD_MUTED}">
      <div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h4 class="font-sans text-base font-semibold text-foreground">Embedding model</h4>
          <p class="mt-1 text-sm text-muted-foreground">
            Default: <em>{ctrl.draft.knowledge.default_embedding_model_resolved}</em>
          </p>
        </div>
        {#if ctrl.draft.knowledge.default_embedding_model_locked}
          <Badge variant="outline">Locked while indexed</Badge>
        {/if}
      </div>
      <SingleModelPicker
        label="Knowledge embedding model"
        hint="Null uses the local multilingual FastEmbed default shown above."
        selectedId={ctrl.draft.knowledge.default_embedding_model}
        catalogModels={ctrl.embeddingOptions}
        catalogAllProviders={ctrl.catalogAllProviders}
        workspaceActiveProvidersResolved={ctrl.activeProvidersStore.resolved}
        workspaceActiveProviderIds={ctrl.activeProvidersStore.embeddingActiveProviderIds}
        busy={ctrl.busy || Boolean(ctrl.draft.knowledge.default_embedding_model_locked)}
        emptyProviders="No embedding providers in catalog."
        emptyModelsForProvider="No embedding models for this provider."
        onSelect={ctrl.setKnowledgeEmbeddingModel}
        onChange={ctrl.markDirty}
      />
    </div>

    <div class="grid gap-3 {ADMIN_SECTION_CARD_MUTED}">
      <h4 class="font-sans text-base font-semibold text-foreground">Retrieval defaults</h4>
      <div class="grid gap-3 md:grid-cols-2">
        <FormField label="Results per query">
          <input
            type="number"
            min="1"
            max="100"
            class={ADMIN_SELECT_LG}
            bind:value={ctrl.draft.knowledge.retrieval.top_k}
            oninput={ctrl.markDirty}
          />
        </FormField>
        <FormField label="Minimum score">
          <input
            type="number"
            min="0"
            max="1"
            step="0.05"
            class={ADMIN_SELECT_LG}
            bind:value={ctrl.draft.knowledge.retrieval.min_score}
            oninput={ctrl.markDirty}
          />
        </FormField>
      </div>
    </div>

    <FormField label="Default knowledge answering tuning profile" class="max-w-md">
      <select
        class={ADMIN_SELECT_LG}
        value={ctrl.draft.knowledge.default_tuning_profile}
        onchange={(event) => ctrl.setDefaultTuningProfile('knowledge', event.currentTarget.value)}
      >
        {#each ctrl.profileEntries as [id, profile] (id)}
          <option value={id}>{profile.label}</option>
        {/each}
      </select>
    </FormField>

    <SingleModelPicker
      label="Knowledge answering model"
      hint={knowledgeAnsweringModelHint(ctrl.draft)}
      selectedId={ctrl.draft.knowledge.answering.model}
      catalogModels={ctrl.chatOptions}
      catalogAllProviders={ctrl.catalogAllProviders}
      workspaceActiveProvidersResolved={ctrl.activeProvidersStore.resolved}
      workspaceActiveProviderIds={ctrl.activeProvidersStore.chatActiveProviderIds}
      busy={ctrl.busy}
      emptyProviders="No chat providers in catalog."
      emptyModelsForProvider="No chat models for this provider."
      onSelect={ctrl.setKnowledgeAnswerModel}
      onChange={ctrl.markDirty}
    />

    <div class="grid gap-3 {ADMIN_SECTION_CARD_MUTED}">
      <h4 class="font-sans text-base font-semibold text-foreground">Answering and chunking</h4>
      <label class="flex min-h-10 items-center gap-3 rounded-md border border-border/50 bg-card/45 px-3">
        <input
          type="checkbox"
          bind:checked={ctrl.draft.knowledge.answering.cite_sources}
          onchange={ctrl.markDirty}
        />
        <span class="font-sans text-sm font-medium">Cite sources</span>
      </label>
      <div class="grid gap-3 md:grid-cols-3">
        <FormField label="Language policy">
          <select
            class={ADMIN_SELECT_LG}
            bind:value={ctrl.draft.knowledge.answering.language_policy}
            onchange={ctrl.markDirty}
          >
            <option value="match_query">Match query</option>
            <option value="prefer_english">Prefer English</option>
            <option value="prefer_arabic">Prefer Arabic</option>
          </select>
        </FormField>
        <FormField label="Chunk size">
          <input
            type="number"
            min="200"
            max="8000"
            class={ADMIN_SELECT_LG}
            bind:value={ctrl.draft.knowledge.chunking.chunk_size}
            oninput={ctrl.markDirty}
          />
        </FormField>
        <FormField label="Chunk overlap">
          <input
            type="number"
            min="0"
            max="2000"
            class={ADMIN_SELECT_LG}
            bind:value={ctrl.draft.knowledge.chunking.chunk_overlap}
            oninput={ctrl.markDirty}
          />
        </FormField>
      </div>
      <label class="flex min-h-10 items-center gap-3 rounded-md border border-border/50 bg-card/45 px-3">
        <input
          type="checkbox"
          bind:checked={ctrl.draft.knowledge.chunking.markdown.respect_headings}
          onchange={ctrl.markDirty}
        />
        <span class="font-sans text-sm font-medium">Respect markdown headings</span>
      </label>
    </div>
  {/if}
</section>
