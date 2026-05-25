<script lang="ts">
  import Badge from '$lib/components/ui/badge.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import SectionCardMuted from '$lib/components/page/SectionCardMuted.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { knowledgeAnsweringModelHint } from '$lib/features/preferences/shared/preferences-helpers';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import {
    PREFERENCE_TAB_IDS,
    PREFERENCE_TAB_PANEL_IDS
  } from '$lib/features/preferences/shared/preferences-tabs';
  import { ADMIN_SELECT_LG } from '$lib/features/preferences/shared/preferences-ui';
  import SingleModelPicker from '$lib/features/preferences/SingleModelPicker.svelte';
  import ActiveProvidersLink from '$lib/features/preferences/widgets/ActiveProvidersLink.svelte';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();
</script>

<div
  id={PREFERENCE_TAB_PANEL_IDS.knowledge}
  class="grid gap-4"
  role="tabpanel"
  aria-labelledby={PREFERENCE_TAB_IDS.knowledge}
>
  <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
    {#if ctrl.sectionDescription('knowledge')}
      <p class="min-w-0 flex-1 text-sm text-muted-foreground">{ctrl.sectionDescription('knowledge')}</p>
    {/if}
    <ActiveProvidersLink busy={ctrl.busy} />
  </div>

  {#if ctrl.draft}
    <SectionCardMuted
      title="Embedding model"
      description={`Default: ${ctrl.draft.knowledge.default_embedding_model_resolved}`}
      collapsible
      bodyId={PREFERENCES_SECTION_BODY_IDS.knowledgeEmbedding}
    >
      {#snippet headerActions()}
        {#if ctrl.draft?.knowledge.default_embedding_model_locked}
          <Badge variant="outline">Locked while indexed</Badge>
        {/if}
      {/snippet}
      <SingleModelPicker
        embedded
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
    </SectionCardMuted>

    <SectionCardMuted
      title="Retrieval defaults"
      collapsible
      bodyId={PREFERENCES_SECTION_BODY_IDS.knowledgeRetrieval}
    >
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
    </SectionCardMuted>

    <SectionCardMuted
      title="Default knowledge answering tuning profile"
      collapsible
      bodyId={PREFERENCES_SECTION_BODY_IDS.knowledgeTuningProfile}
    >
      <FormField label="Profile" class="max-w-md">
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
    </SectionCardMuted>

    <SectionCardMuted
      title="Knowledge answering model"
      description={knowledgeAnsweringModelHint(ctrl.draft)}
      collapsible
      bodyId={PREFERENCES_SECTION_BODY_IDS.knowledgeAnsweringModel}
    >
      <SingleModelPicker
        embedded
        label="Knowledge answering model"
        hint=""
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
    </SectionCardMuted>

    <SectionCardMuted
      title="Answering and chunking"
      collapsible
      bodyId={PREFERENCES_SECTION_BODY_IDS.knowledgeAnsweringChunking}
    >
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
    </SectionCardMuted>
  {/if}
</div>
