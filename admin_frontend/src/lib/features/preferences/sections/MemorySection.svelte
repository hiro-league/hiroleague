<script lang="ts">
  import FormField from '$lib/components/ui/form-field.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import {
    rerankerDeviceOptions,
    rerankerModelOptions
  } from '$lib/features/preferences/shared/preferences-constants';
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

<section id="preferences-memory" class="{PREFERENCE_SECTION_SCROLL_MT} grid gap-4 border-b pb-6">
  <div>
    <h3 class="font-sans text-xl font-semibold text-foreground">
      {ctrl.sectionLabel('memory', 'Agent Memory')}
    </h3>
    <p class="mt-1 text-sm text-muted-foreground">{ctrl.sectionDescription('memory')}</p>
  </div>

  {#if ctrl.draft}
    <SingleModelPicker
      label="Memory LLM model"
      hint="Used by the memory service for memory extraction."
      selectedId={ctrl.draft.memory.default_llm}
      catalogModels={ctrl.memoryLlmOptions}
      catalogAllProviders={ctrl.catalogAllProviders}
      workspaceActiveProvidersResolved={ctrl.activeProvidersStore.resolved}
      workspaceActiveProviderIds={ctrl.activeProvidersStore.chatActiveProviderIds}
      busy={ctrl.busy}
      emptyProviders="No chat providers in catalog."
      emptyModelsForProvider="No chat models for this provider."
      onSelect={(id) => ctrl.setMemoryModel('default_llm', id)}
      onChange={ctrl.markDirty}
    />

    <SingleModelPicker
      label="Memory embedding model"
      hint="Used by the memory service for vector search."
      selectedId={ctrl.draft.memory.default_embedding_model}
      catalogModels={ctrl.embeddingOptions}
      catalogAllProviders={ctrl.catalogAllProviders}
      workspaceActiveProvidersResolved={ctrl.activeProvidersStore.resolved}
      workspaceActiveProviderIds={ctrl.activeProvidersStore.embeddingActiveProviderIds}
      busy={ctrl.busy}
      emptyProviders="No embedding providers in catalog."
      emptyModelsForProvider="No embedding models for this provider."
      onSelect={(id) => ctrl.setMemoryModel('default_embedding_model', id)}
      onChange={ctrl.markDirty}
    />

    <FormField label="Max retained messages" class="max-w-sm">
      <input
        type="number"
        min="1"
        max="100"
        class={ADMIN_SELECT_LG}
        bind:value={ctrl.draft.memory.max_messages}
        oninput={ctrl.markDirty}
      />
    </FormField>

    <FormField label="Default memory tuning profile" class="max-w-md">
      <select
        class={ADMIN_SELECT_LG}
        value={ctrl.draft.memory.default_tuning_profile}
        onchange={(event) => ctrl.setDefaultTuningProfile('memory', event.currentTarget.value)}
      >
        {#each ctrl.profileEntries as [id, profile] (id)}
          <option value={id}>{profile.label}</option>
        {/each}
      </select>
    </FormField>

    <div class="grid gap-3 {ADMIN_SECTION_CARD_MUTED}">
      <div>
        <h4 class="font-sans text-base font-semibold text-foreground">Local reranker</h4>
        <p class="mt-1 text-sm text-muted-foreground">
          Optional cross-encoder reranking (sentence-transformers). Downloads the model on first use.
          Rebuilds the memory service when saved.
        </p>
      </div>
      <label class="flex min-h-10 items-center gap-3 rounded-md border border-border/50 bg-card/45 px-3">
        <input
          type="checkbox"
          checked={ctrl.draft.memory.reranker.enabled}
          disabled={ctrl.busy}
          onchange={(event) => ctrl.setRerankerEnabled(event.currentTarget.checked)}
        />
        <span class="font-sans text-sm font-medium">Enable local reranker</span>
      </label>
      <div class="grid gap-3 md:grid-cols-2">
        <FormField label="Cross-encoder model">
          <select
            class={ADMIN_SELECT_LG}
            value={ctrl.draft.memory.reranker.model}
            disabled={ctrl.busy || !ctrl.memoryRerankerEnabled}
            onchange={(event) => ctrl.setRerankerModel(event.currentTarget.value)}
          >
            {#each rerankerModelOptions as option (option.id)}
              <option value={option.id}>{option.label}</option>
            {/each}
          </select>
        </FormField>
        <FormField label="Device">
          <select
            class={ADMIN_SELECT_LG}
            value={ctrl.rerankerDeviceValue(ctrl.draft.memory.reranker.device)}
            disabled={ctrl.busy || !ctrl.memoryRerankerEnabled}
            onchange={(event) => ctrl.setRerankerDevice(event.currentTarget.value)}
          >
            {#each rerankerDeviceOptions as option (option.value)}
              <option value={option.value}>{option.label}</option>
            {/each}
          </select>
        </FormField>
      </div>
      <FormField label="Batch size" class="max-w-sm">
        <input
          type="number"
          min="1"
          max="512"
          step="1"
          class={ADMIN_SELECT_LG}
          bind:value={ctrl.draft.memory.reranker.batch_size}
          disabled={ctrl.busy || !ctrl.memoryRerankerEnabled}
          oninput={ctrl.markDirty}
        />
      </FormField>
    </div>

    <div class="grid gap-3 {ADMIN_SECTION_CARD_MUTED}">
      <div>
        <h4 class="font-sans text-base font-semibold text-foreground">Retrieval</h4>
        <p class="mt-1 text-sm text-muted-foreground">
          Controls long-term memory search before each reply (memory_in). Rebuilds the memory service when
          saved.
        </p>
      </div>
      <div class="grid gap-3 md:grid-cols-2">
        <FormField label="Results per search">
          <input
            type="number"
            min="1"
            max="100"
            step="1"
            class={ADMIN_SELECT_LG}
            bind:value={ctrl.draft.memory.search.top_k}
            disabled={ctrl.busy}
            oninput={ctrl.markDirty}
          />
        </FormField>
        <FormField label="Minimum relevance">
          <input
            type="number"
            min="0"
            max="1"
            step="0.05"
            class={ADMIN_SELECT_LG}
            bind:value={ctrl.draft.memory.search.threshold}
            disabled={ctrl.busy}
            oninput={ctrl.markDirty}
          />
          <span class="text-xs text-muted-foreground">Score 0–1; use 0 to disable filtering.</span>
        </FormField>
      </div>
      <label
        class="flex min-h-10 items-center gap-3 rounded-md border border-border/50 bg-card/45 px-3 {!ctrl.memoryRerankerEnabled
          ? 'opacity-50'
          : ''}"
      >
        <input
          type="checkbox"
          bind:checked={ctrl.draft.memory.search.rerank}
          disabled={ctrl.busy || !ctrl.memoryRerankerEnabled}
          onchange={ctrl.markDirty}
        />
        <span class="font-sans text-sm font-medium">Rerank search results</span>
      </label>
      {#if !ctrl.memoryRerankerEnabled}
        <p class="text-xs text-muted-foreground">Enable the local reranker above to use reranking.</p>
      {/if}
    </div>
  {/if}
</section>
