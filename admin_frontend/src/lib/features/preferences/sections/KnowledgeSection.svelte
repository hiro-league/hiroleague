<script lang="ts">
  import Badge from '$lib/components/ui/badge.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import MarkdownEditorPreview from '$lib/components/ui/markdown/MarkdownEditorPreview.svelte';
  import SectionCardMuted from '$lib/components/page/SectionCardMuted.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { knowledgeAnsweringModelHint, knowledgeHybridPrefetchActive, knowledgeRerankTopNActive } from '$lib/features/preferences/shared/preferences-helpers';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import {
    PREFERENCE_TAB_IDS,
    PREFERENCE_TAB_PANEL_IDS
  } from '$lib/features/preferences/shared/preferences-tabs';
  import { ADMIN_SELECT_LG } from '$lib/features/preferences/shared/preferences-ui';
  import SingleModelPicker from '$lib/features/preferences/SingleModelPicker.svelte';
  import ActiveProvidersLink from '$lib/features/preferences/widgets/ActiveProvidersLink.svelte';
  import KnowledgeBrowseLink from '$lib/features/preferences/widgets/KnowledgeBrowseLink.svelte';
  import { cn } from '$lib/utils';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();

  const hybridPrefetchActive = $derived(knowledgeHybridPrefetchActive(ctrl.draft));
  const rerankTopNActive = $derived(
    knowledgeRerankTopNActive(
      ctrl.draft,
      ctrl.localRerankers,
      ctrl.activeProvidersStore.resolved,
      ctrl.activeProvidersStore.rerankActiveProviderIds
    )
  );
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
    <div class="flex shrink-0 flex-wrap items-center justify-end gap-2">
      <KnowledgeBrowseLink busy={ctrl.busy} />
      <ActiveProvidersLink busy={ctrl.busy} />
    </div>
  </div>

  {#if ctrl.draft}
    <SectionCardMuted
      title="Embedding and Chunking"
      description={`Default embedding model: ${ctrl.draft.knowledge.default_embedding_model_resolved}. Chunking settings apply at document ingest.`}
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
      <div class="grid gap-3 md:grid-cols-2">
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
      <label class="flex items-start gap-3 rounded-md border border-border/50 bg-card/45 px-3 py-2.5">
        <input
          type="checkbox"
          class="mt-0.5"
          bind:checked={ctrl.draft.knowledge.chunking.embed_structural_context}
          onchange={ctrl.markDirty}
        />
        <span class="grid gap-0.5">
          <span class="font-sans text-sm font-medium">Embed structural context</span>
          <span class="font-sans text-xs text-muted-foreground">
            Prefix each chunk's embedded text with its document title and heading path so every chunk
            — including continuation pieces — carries its section context. Applies to new ingests;
            changing this requires re-ingesting existing documents.
          </span>
        </span>
      </label>
    </SectionCardMuted>

    <SectionCardMuted
      title="Retrieval defaults"
      collapsible
      bodyId={PREFERENCES_SECTION_BODY_IDS.knowledgeRetrieval}
    >
      <label class="flex min-h-10 items-center gap-3 rounded-md border border-border/50 bg-card/45 px-3">
        <input
          type="checkbox"
          bind:checked={ctrl.draft.knowledge.retrieval.hybrid}
          onchange={ctrl.markDirty}
        />
        <span class="font-sans text-sm font-medium">Hybrid retrieval (dense + BM25, RRF fusion)</span>
      </label>
      <p class="text-xs text-muted-foreground">
        Runs BM25 keyword search alongside dense embeddings and fuses them with Reciprocal Rank
        Fusion — recovers exact terms, proper nouns, and Arabic surface forms. Sparse model:
        <code>{ctrl.draft.knowledge.retrieval.sparse_model}</code> (local, no extra setup).
      </p>
      <div class="grid gap-3">
        <label class="flex flex-wrap items-center gap-x-3 gap-y-2">
          <span class="w-60 shrink-0 font-sans text-sm font-semibold text-muted-foreground"
            >Minimum score (Dense only)</span
          >
          <input
            type="number"
            min="0"
            max="1"
            step="0.05"
            class="{ADMIN_SELECT_LG} w-28 shrink-0"
            bind:value={ctrl.draft.knowledge.retrieval.min_score}
            oninput={ctrl.markDirty}
          />
          <span class="min-w-0 flex-1 font-sans text-xs text-muted-foreground"
            >Applies only to dense (Vector search) branch</span
          >
        </label>
        <label
          class={cn(
            'flex flex-wrap items-center gap-x-3 gap-y-2',
            !hybridPrefetchActive && 'opacity-50'
          )}
        >
          <span class="w-60 shrink-0 font-sans text-sm font-semibold text-muted-foreground"
            >Candidates per branch</span
          >
          <input
            type="number"
            min="1"
            max="500"
            class="{ADMIN_SELECT_LG} w-28 shrink-0"
            bind:value={ctrl.draft.knowledge.retrieval.prefetch_limit}
            disabled={ctrl.busy || !hybridPrefetchActive}
            oninput={ctrl.markDirty}
          />
          <span class="min-w-0 flex-1 font-sans text-xs text-muted-foreground"
            >Results to return for dense(Vector) or sparse(BM25) separately, before RRF fusion
            (Hybrid Only)</span
          >
        </label>
        <label class="flex flex-wrap items-center gap-x-3 gap-y-2">
          <span class="w-60 shrink-0 font-sans text-sm font-semibold text-muted-foreground"
            >Search/fused results (top K)</span
          >
          <input
            type="number"
            min="1"
            max="100"
            class="{ADMIN_SELECT_LG} w-28 shrink-0"
            bind:value={ctrl.draft.knowledge.retrieval.top_k}
            oninput={ctrl.markDirty}
          />
          <span class="min-w-0 flex-1 font-sans text-xs text-muted-foreground"
            >Fused results from hybrid search or direct results from dense only search (after applying
            minimum score)</span
          >
        </label>
        <label
          class={cn('flex flex-wrap items-center gap-x-3 gap-y-2', !rerankTopNActive && 'opacity-50')}
        >
          <span class="w-60 shrink-0 font-sans text-sm font-semibold text-muted-foreground"
            >Rerank results (top N)</span
          >
          <input
            type="number"
            min="1"
            max="100"
            class="{ADMIN_SELECT_LG} w-28 shrink-0"
            bind:value={ctrl.draft.knowledge.retrieval.reranker.top_n}
            disabled={ctrl.busy || !rerankTopNActive}
            oninput={ctrl.markDirty}
          />
          <span class="min-w-0 flex-1 font-sans text-xs text-muted-foreground"
            >Final returned results if using rerank (top N)</span
          >
        </label>
      </div>
    </SectionCardMuted>

    <SectionCardMuted
      title="Reranker"
      description="Optional cross-encoder that reorders retrieved candidates by relevance before answering (precision step). Default off. Cloud models need a provider key; local models must be downloaded first. Switching is a hot swap — no re-ingest."
      collapsible
      bodyId={PREFERENCES_SECTION_BODY_IDS.knowledgeReranker}
    >
      <label class="flex min-h-10 items-center gap-3 rounded-md border border-border/50 bg-card/45 px-3">
        <input
          type="checkbox"
          bind:checked={ctrl.draft.knowledge.retrieval.reranker.enabled}
          onchange={ctrl.markDirty}
        />
        <span class="font-sans text-sm font-medium">Enable reranking</span>
      </label>
      <SingleModelPicker
        embedded
        label="Reranker model"
        hint=""
        selectedId={ctrl.draft.knowledge.retrieval.reranker.model_id}
        catalogModels={ctrl.rerankPickerOptions}
        catalogAllProviders={ctrl.catalogAllProviders}
        workspaceActiveProvidersResolved={ctrl.activeProvidersStore.resolved}
        workspaceActiveProviderIds={ctrl.activeProvidersStore.rerankActiveProviderIds}
        busy={ctrl.busy}
        emptyProviders="No reranker providers."
        emptyModelsForProvider="No reranker models for this provider."
        onSelect={ctrl.setKnowledgeRerankerModel}
        onChange={ctrl.markDirty}
      />

      {#if ctrl.draft.knowledge.retrieval.reranker.model_id}
        {@const sel = ctrl.localRerankers.find(
          (m) => m.id === ctrl.draft?.knowledge.retrieval.reranker.model_id
        )}
        {#if sel && !(sel.downloaded || sel.status === 'ready')}
          {@const downloading = sel.status === 'downloading' || ctrl.rerankerDownloading === sel.id}
          <div class="grid gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2">
            <div class="flex items-center justify-between gap-3">
              <div class="min-w-0 font-sans text-xs">
                <span class="font-medium">
                  {downloading ? 'Downloading…' : "This local model isn't downloaded yet"}
                </span>
                <span class="text-muted-foreground">
                  · {sel.size_label}{#if downloading && sel.percent != null} · {sel.percent}%{/if}
                </span>
                {#if sel.status === 'error' && sel.error}
                  <div class="text-destructive">{sel.error}</div>
                {/if}
              </div>
              <div class="shrink-0">
                {#if downloading}
                  <Button variant="outline" size="sm" onclick={() => ctrl.cancelReranker(sel.id)}>
                    Cancel
                  </Button>
                {:else}
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={ctrl.busy || ctrl.rerankerBusy}
                    onclick={() => ctrl.downloadReranker(sel.id)}
                  >
                    {sel.status === 'error' ? 'Retry download' : 'Download'}
                  </Button>
                {/if}
              </div>
            </div>
            {#if downloading}
              <div class="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                <div
                  class="h-full rounded-full bg-amber-500 transition-[width] duration-500"
                  style="width: {sel.percent ?? 3}%"
                ></div>
              </div>
            {/if}
          </div>
        {/if}
      {/if}

      <p class="text-xs text-muted-foreground">
        Cloud scores are calibrated <code>[0,1]</code>; local cross-encoder scores are
        sigmoid-normalized. A normalized <code>relevance</code> is emitted whether reranking is on
        (reranker score) or off (retrieval rank), so downstream ranking stays consistent.
      </p>
    </SectionCardMuted>

    <SectionCardMuted
      title="Query Rewrite (Ask Tab/Chat Agent)"
      description="Optional LLM step that rewrites a question before retrieval — normalizes wording and extracts literal keywords. Reuses the answering model; toggled per query on the Ask tab."
      collapsible
      bodyId={PREFERENCES_SECTION_BODY_IDS.knowledgeRewrite}
    >
      <label class="flex min-h-10 items-center gap-3 rounded-md border border-border/50 bg-card/45 px-3">
        <input
          type="checkbox"
          bind:checked={ctrl.draft.knowledge.rewrite.default_on}
          onchange={ctrl.markDirty}
        />
        <span class="font-sans text-sm font-medium">Enable by default on the Ask tab</span>
      </label>
      <MarkdownEditorPreview
        editorLabel="Rewrite prompt editor"
        previewLabel="Preview"
        ariaLabel="Knowledge query rewrite prompt (markdown)"
        bind:value={ctrl.draft.knowledge.rewrite.prompt}
        onInput={ctrl.markDirty}
      />
      <p class="text-xs text-muted-foreground">
        Sent as the system prompt for the rewrite call. Keep the instruction to copy proper nouns
        and identifiers verbatim so the BM25 keyword branch keeps its exact-match signal.
      </p>
    </SectionCardMuted>

    <SectionCardMuted
      title="Knowledge answering (Ask Tab only)"
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
      <FormField label="Knowledge answering model profile" class="max-w-md">
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
      <label class="flex min-h-10 items-center gap-3 rounded-md border border-border/50 bg-card/45 px-3">
        <input
          type="checkbox"
          bind:checked={ctrl.draft.knowledge.answering.cite_sources}
          onchange={ctrl.markDirty}
        />
        <span class="font-sans text-sm font-medium">Cite sources</span>
      </label>
      <FormField label="Language policy" class="max-w-md">
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
    </SectionCardMuted>

    <SectionCardMuted
      title="Knowledge Graph (Graphiti)"
      description="Temporal entity/fact graph over the workspace knowledge. When on, retrieval focuses on graph-relevant chunks (and temporal facts). Build the graph from a document on the Add tab first. Off = flat Qdrant retrieval only."
      collapsible
      bodyId={PREFERENCES_SECTION_BODY_IDS.knowledgeGraph}
    >
      <FormField label="Graph backend" class="max-w-md">
        <select
          class={ADMIN_SELECT_LG}
          bind:value={ctrl.draft.knowledge.graph.backend}
          onchange={ctrl.markDirty}
        >
          <option value="off">Off — flat Qdrant only</option>
          <option value="graphiti">Graphiti — graph facts</option>
          <option value="mix">Mix — graph focuses Qdrant passages (recommended)</option>
        </select>
      </FormField>

      <SingleModelPicker
        embedded
        label="Graph extraction model"
        hint="Structured-output-capable chat model (Graphiti extraction). Null falls back to the answering model / default chat."
        selectedId={ctrl.draft.knowledge.graph.extraction_model}
        catalogModels={ctrl.chatOptions}
        catalogAllProviders={ctrl.catalogAllProviders}
        workspaceActiveProvidersResolved={ctrl.activeProvidersStore.resolved}
        workspaceActiveProviderIds={ctrl.activeProvidersStore.chatActiveProviderIds}
        busy={ctrl.busy}
        emptyProviders="No chat providers in catalog."
        emptyModelsForProvider="No chat models for this provider."
        onSelect={ctrl.setKnowledgeGraphExtractionModel}
        onChange={ctrl.markDirty}
      />
      <FormField label="Graph extraction profile" class="max-w-md">
        <select
          class={ADMIN_SELECT_LG}
          bind:value={ctrl.draft.knowledge.graph.extraction_tuning_profile}
          onchange={ctrl.markDirty}
        >
          {#each ctrl.profileEntries as [id, profile] (id)}
            <option value={id}>{profile.label}</option>
          {/each}
        </select>
      </FormField>

      <SingleModelPicker
        embedded
        label="Graph small-step model"
        hint="Cheaper model for dedupe / summaries / timestamps. Null falls back to the extraction model."
        selectedId={ctrl.draft.knowledge.graph.small_model}
        catalogModels={ctrl.chatOptions}
        catalogAllProviders={ctrl.catalogAllProviders}
        workspaceActiveProvidersResolved={ctrl.activeProvidersStore.resolved}
        workspaceActiveProviderIds={ctrl.activeProvidersStore.chatActiveProviderIds}
        busy={ctrl.busy}
        emptyProviders="No chat providers in catalog."
        emptyModelsForProvider="No chat models for this provider."
        onSelect={ctrl.setKnowledgeGraphSmallModel}
        onChange={ctrl.markDirty}
      />
      <FormField label="Graph small-step profile" class="max-w-md">
        <select
          class={ADMIN_SELECT_LG}
          bind:value={ctrl.draft.knowledge.graph.small_tuning_profile}
          onchange={ctrl.markDirty}
        >
          {#each ctrl.profileEntries as [id, profile] (id)}
            <option value={id}>{profile.label}</option>
          {/each}
        </select>
      </FormField>

      <SingleModelPicker
        embedded
        label="Graph embedder"
        hint="Embeds entity names + facts into the graph. Null shares the knowledge embedding model above."
        selectedId={ctrl.draft.knowledge.graph.embedder_model}
        catalogModels={ctrl.embeddingOptions}
        catalogAllProviders={ctrl.catalogAllProviders}
        workspaceActiveProvidersResolved={ctrl.activeProvidersStore.resolved}
        workspaceActiveProviderIds={ctrl.activeProvidersStore.embeddingActiveProviderIds}
        busy={ctrl.busy}
        emptyProviders="No embedding providers in catalog."
        emptyModelsForProvider="No embedding models for this provider."
        onSelect={ctrl.setKnowledgeGraphEmbedderModel}
        onChange={ctrl.markDirty}
      />

      <div class="grid gap-3 md:grid-cols-2">
        <FormField label="Temporal lens (default)">
          <select
            class={ADMIN_SELECT_LG}
            bind:value={ctrl.draft.knowledge.graph.temporal_default}
            onchange={ctrl.markDirty}
          >
            <option value="current">Current facts only</option>
            <option value="all">Include historical</option>
          </select>
        </FormField>
        <FormField label="Expansion hops (k)">
          <input
            type="number"
            min="1"
            max="3"
            class={ADMIN_SELECT_LG}
            bind:value={ctrl.draft.knowledge.graph.k_hop}
            oninput={ctrl.markDirty}
          />
        </FormField>
      </div>
      <FormField label="Search recipe" class="max-w-md">
        <select
          class={ADMIN_SELECT_LG}
          bind:value={ctrl.draft.knowledge.graph.search_recipe}
          onchange={ctrl.markDirty}
        >
          <option value="rrf">RRF</option>
          <option value="mmr">MMR</option>
          <option value="cross_encoder">Cross-encoder</option>
        </select>
      </FormField>
      <label class="flex items-start gap-3 rounded-md border border-border/50 bg-card/45 px-3 py-2.5">
        <input
          type="checkbox"
          class="mt-0.5"
          bind:checked={ctrl.draft.knowledge.graph.communities_enabled}
          onchange={ctrl.markDirty}
        />
        <span class="grid gap-0.5">
          <span class="font-sans text-sm font-medium">Communities (advanced)</span>
          <span class="font-sans text-xs text-muted-foreground">
            Cluster entities into community summaries. Off by default — extra LLM cost; experimental.
          </span>
        </span>
      </label>
    </SectionCardMuted>
  {/if}
</div>
