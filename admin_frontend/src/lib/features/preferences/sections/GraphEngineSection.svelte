<script lang="ts">
  import FormField from '$lib/components/ui/form-field.svelte';
  import SectionCardMuted from '$lib/components/page/SectionCardMuted.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
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
  id={PREFERENCE_TAB_PANEL_IDS['graph-engine']}
  class="grid gap-4"
  role="tabpanel"
  aria-labelledby={PREFERENCE_TAB_IDS['graph-engine']}
>
  <div class="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
    <p class="min-w-0 flex-1 text-sm text-muted-foreground">
      One Graphiti temporal-graph engine, shared by <span class="font-medium">Agent Memory</span> and
      <span class="font-medium">Knowledge</span> — these models and graph-search settings apply to
      both. (Whether Knowledge <em>retrieval</em> uses the graph is the "Graph backend" toggle on the
      Knowledge tab.) Changing the graph embedder re-indexes all graph data.
    </p>
    <ActiveProvidersLink busy={ctrl.busy} />
  </div>

  {#if ctrl.draft}
    <SectionCardMuted
      title="Graph engine (Graphiti)"
      description="Temporal entity/fact graph over the workspace. Models read each chunk/turn and pull out entities + dated facts; the graph search ranks those facts at retrieval time."
      collapsible
      bodyId={PREFERENCES_SECTION_BODY_IDS.graphEngine}
    >
      <SingleModelPicker
        embedded
        labelled
        label="Graph extraction model"
        hint="The heavy LLM Graphiti uses to read each chunk/turn and pull out entities + facts. Must be structured-output-capable. Null falls back to the answering model, then default chat."
        selectedId={ctrl.draft.graph.extraction_model}
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
      <FormField
        label="Graph extraction profile"
        hint="Tuning profile (temperature / max-tokens / thinking) for the extraction model. Ships deterministic so extraction stays repeatable across runs."
        class="max-w-md"
      >
        <select
          class={ADMIN_SELECT_LG}
          bind:value={ctrl.draft.graph.extraction_tuning_profile}
          onchange={ctrl.markDirty}
        >
          {#each ctrl.profileEntries as [id, profile] (id)}
            <option value={id}>{profile.label}</option>
          {/each}
        </select>
      </FormField>

      <SingleModelPicker
        embedded
        labelled
        label="Graph small-step model"
        hint="Cheaper model for dedupe / summaries / timestamps. Null falls back to the extraction model."
        selectedId={ctrl.draft.graph.small_model}
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
      <FormField
        label="Graph small-step profile"
        hint="Tuning profile for the cheaper small-step model (dedupe / summaries / timestamps)."
        class="max-w-md"
      >
        <select
          class={ADMIN_SELECT_LG}
          bind:value={ctrl.draft.graph.small_tuning_profile}
          onchange={ctrl.markDirty}
        >
          {#each ctrl.profileEntries as [id, profile] (id)}
            <option value={id}>{profile.label}</option>
          {/each}
        </select>
      </FormField>

      <SingleModelPicker
        embedded
        labelled
        label="Graph embedder"
        hint="Embeds entity names + facts into the graph. Null shares the knowledge embedding model. Shared across memory + knowledge graph data — changing it re-indexes everything."
        selectedId={ctrl.draft.graph.embedder_model}
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
        <FormField
          label="Temporal lens (default)"
          hint="Default time lens at retrieval. Current = only facts valid now (superseded facts hidden). Include historical = also surface invalidated facts. Overridable per query."
        >
          <select
            class={ADMIN_SELECT_LG}
            bind:value={ctrl.draft.graph.temporal_default}
            onchange={ctrl.markDirty}
          >
            <option value="current">Current facts only</option>
            <option value="all">Include historical</option>
          </select>
        </FormField>
        <FormField
          label="Expansion hops (k)"
          hint="Relationship hops out from matched entities when gathering related facts. 1 = direct neighbors only (precise); higher reaches further at more noise/cost."
        >
          <input
            type="number"
            min="1"
            max="3"
            class={ADMIN_SELECT_LG}
            bind:value={ctrl.draft.graph.k_hop}
            oninput={ctrl.markDirty}
          />
        </FormField>
      </div>
      <div class="grid gap-4 md:grid-cols-2">
        <FormField
          label="Search recipe"
          hint="How candidates are ranked/fused WITHIN each leg (orthogonal to Search scope below). RRF = fast reciprocal-rank fusion (default). MMR = favors diversity. Cross-encoder = highest quality, slowest/most costly. MMR is not compatible with the episodes leg (BM25-only) — disabled when scope includes episodes."
        >
          <select
            class={ADMIN_SELECT_LG}
            bind:value={ctrl.draft.graph.search_recipe}
            onchange={ctrl.markDirty}
          >
            <option value="rrf">RRF</option>
            <option
              value="mmr"
              disabled={ctrl.draft.graph.search_scope === 'edges_nodes_episodes'}
              title={ctrl.draft.graph.search_scope === 'edges_nodes_episodes'
                ? 'MMR is not supported when scope includes episodes (episodes are BM25-only and EpisodeReranker has no MMR). Switch scope, or pick RRF / Cross-encoder.'
                : ''}
            >
              MMR{ctrl.draft.graph.search_scope === 'edges_nodes_episodes'
                ? ' (n/a with episodes)'
                : ''}
            </option>
            <option value="cross_encoder">Cross-encoder</option>
          </select>
        </FormField>
        <FormField
          label="Search scope"
          hint="Which graph elements memory recall and knowledge retrieval READ from (orthogonal to Search recipe above). Edges = facts between entities (relations). Nodes = per-entity summaries (attribute-style memories, e.g. age, role, mood). Episodes = the raw conversation text of each saved turn — BM25 keyword match only (paraphrases may miss), useful as last-resort recall."
        >
          <select
            class={ADMIN_SELECT_LG}
            bind:value={ctrl.draft.graph.search_scope}
            onchange={ctrl.markDirty}
          >
            <option value="edges">Edges (facts only)</option>
            <option value="edges_and_nodes">Edges + Nodes</option>
            <option
              value="edges_nodes_episodes"
              disabled={ctrl.draft.graph.search_recipe === 'mmr'}
              title={ctrl.draft.graph.search_recipe === 'mmr'
                ? 'Episodes leg is BM25-only and EpisodeReranker has no MMR. Switch recipe to RRF or Cross-encoder, then select this scope.'
                : ''}
            >
              Edges + Nodes + Episodes{ctrl.draft.graph.search_recipe === 'mmr'
                ? ' (n/a with MMR)'
                : ''}
            </option>
          </select>
        </FormField>
      </div>
      <div class="grid gap-4 md:grid-cols-2">
        <FormField
          label="Candidate similarity floor"
          hint="Minimum cosine similarity (0–1) for a fact to even become a search candidate. Keep low (≈0.3) for recall — too high and paraphrased questions (e.g. asking 'wife' when the stored fact says 'married to') return no facts at all. Graphiti's own default is a strict 0.6. Precision belongs in the reranker's Min relevance below, not here."
        >
          <input
            type="number"
            min="0"
            max="1"
            step="0.05"
            class={ADMIN_SELECT_LG}
            bind:value={ctrl.draft.graph.sim_min_score}
            oninput={ctrl.markDirty}
          />
        </FormField>
      </div>
      <FormField
        label="Graph observability"
        hint="How much the graph engine records to Graph Runs (ingest + retrieval). Off = nothing — no ledger rows, tracer, or usage sinks (spares CPU; graph cost is NOT tracked). Ledger = one priced roll-up row per episode (ingest) and per search (rerank), so token cost still folds into the run total — the production default. Trace = Ledger plus a deep per-stage sidecar (the ⌗ retrieval/ingest trace dialogs) for debugging. Replaces the old Rich/Compact detail and the trace env vars."
        class="max-w-md"
      >
        <select
          class={ADMIN_SELECT_LG}
          bind:value={ctrl.draft.graph.observability}
          onchange={ctrl.markDirty}
        >
          <option value="off">Off (no graph ledger)</option>
          <option value="ledger">Ledger (cost + roll-up · default)</option>
          <option value="trace">Trace (+ deep per-stage sidecars)</option>
        </select>
      </FormField>
    </SectionCardMuted>

    <SectionCardMuted
      title="Graphiti Reranker (Cross-encoder)"
      description="Reranks graph fact-search candidates with a real cross-encoder. Only active when the Search recipe above is set to Cross-encoder — otherwise these settings are disabled. Reuses the same reranker models as the flat path (cloud or local)."
      collapsible
      bodyId={PREFERENCES_SECTION_BODY_IDS.graphEngineReranker}
    >
      {#if ctrl.draft.graph.search_recipe !== 'cross_encoder'}
        <p class="rounded-md border border-border/50 bg-card/45 px-3 py-2 font-sans text-xs text-muted-foreground">
          Set <span class="font-medium">Search recipe → Cross-encoder</span> above to enable these
          settings.
        </p>
      {/if}
      <fieldset
        disabled={ctrl.draft.graph.search_recipe !== 'cross_encoder'}
        class="grid gap-4 border-0 p-0 disabled:opacity-50"
      >
        <SingleModelPicker
          embedded
          label="Reranker model"
          hint="Cross-encoder used to rerank fact candidates. Empty = reuse the knowledge Reranker model (one model to manage). Local models must be downloaded first."
          selectedId={ctrl.draft.graph.reranker.model_id}
          catalogModels={ctrl.rerankPickerOptions}
          catalogAllProviders={ctrl.catalogAllProviders}
          workspaceActiveProvidersResolved={ctrl.activeProvidersStore.resolved}
          workspaceActiveProviderIds={ctrl.activeProvidersStore.rerankActiveProviderIds}
          busy={ctrl.busy}
          emptyProviders="No reranker providers."
          emptyModelsForProvider="No reranker models for this provider."
          onSelect={ctrl.setKnowledgeGraphRerankerModel}
          onChange={ctrl.markDirty}
        />
        <div class="grid gap-3 md:grid-cols-2">
          <FormField
            label="Min relevance"
            hint="Drop facts whose cross-encoder relevance is below this (0–1). 0 = keep all. Ignored by RRF/MMR."
          >
            <input
              type="number"
              min="0"
              max="1"
              step="0.05"
              class={ADMIN_SELECT_LG}
              bind:value={ctrl.draft.graph.reranker.min_relevance}
              oninput={ctrl.markDirty}
            />
          </FormField>
          <FormField
            label="Device (local only)"
            hint="Torch device for local sentence-transformers rerankers (e.g. cpu, cuda). Blank = auto. Ignored by cloud + ONNX models."
          >
            <input
              type="text"
              placeholder="auto"
              class={ADMIN_SELECT_LG}
              bind:value={ctrl.draft.graph.reranker.device}
              oninput={ctrl.markDirty}
            />
          </FormField>
        </div>
      </fieldset>
    </SectionCardMuted>
  {/if}
</div>
