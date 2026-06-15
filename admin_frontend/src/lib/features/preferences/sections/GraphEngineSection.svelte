<script lang="ts">
  import FormField from '$lib/components/ui/form-field.svelte';
  import MarkdownEditorPreview from '$lib/components/ui/markdown/MarkdownEditorPreview.svelte';
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
    <!-- Everything that builds the graph at ingest, in one section. -->
    <SectionCardMuted
      title="Graph Extraction"
      description="Everything that builds the graph at ingest — the entity ontology, the heavy extraction model, the cheaper sub-step model, and the embedder. Changing any of these needs a re-ingest to rebuild the graph."
      collapsible
      bodyId={PREFERENCES_SECTION_BODY_IDS.graphExtraction}
    >
      <FormField
        label="Extraction ontology"
        hint="Which entity types extraction may use. Open = no predefined types; the model extracts freely (everything becomes a generic Entity) — broadest recall, captures activities, interests, media, and preferences. Typed = pin the 5-type vocabulary (Person / Place / Organization / Event / Object) — more precise, but drops first-person facts that don't fit those types. Changing this rebuilds the graph at the next ingest, so a re-ingest is required to take effect."
        class="max-w-md"
      >
        <select
          class={ADMIN_SELECT_LG}
          bind:value={ctrl.draft.graph.entity_ontology}
          onchange={ctrl.markDirty}
        >
          <option value="open">Open (no predefined types)</option>
          <option value="typed">Typed (Person / Place / Organization / Event / Object)</option>
        </select>
      </FormField>

      <FormField
        label="Extraction instructions"
        hint="Optional domain-generic guidance injected verbatim into Graphiti's entity + fact extraction prompts. Use it to steer what gets captured — e.g. capture first-person preferences, goals, habits and activities as facts even when only the speaker is named, treating the activity / topic / object as the second entity. Keep it generic (no dataset-specific rules). Blank = none. Applied at ingest, so a re-ingest is required to take effect."
      >
        <textarea
          class="w-full rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
          rows="4"
          maxlength="2000"
          placeholder="e.g. Capture first-person preferences, goals, habits, and activities as facts even when only the speaker is named; treat the activity, topic, or object as the second entity."
          bind:value={ctrl.draft.graph.custom_extraction_instructions}
          oninput={ctrl.markDirty}
        ></textarea>
      </FormField>

      <SingleModelPicker
        embedded
        labelled
        label="Extraction model"
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
        label="Extraction profile"
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
        label="Smaller extraction model"
        hint="Cheaper model for Graphiti's sub-steps — node dedupe, entity summaries, timestamps. Null falls back to the extraction model."
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
        label="Smaller extraction profile"
        hint="Tuning profile for the cheaper sub-step model (dedupe / summaries / timestamps)."
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
        label="Embedder model"
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
    </SectionCardMuted>

    <SectionCardMuted
      title="Evaluation Models"
      description="Models + profiles the eval harness uses — the answer step (memory track) and the judge (both tracks). Eval-only; the knowledge track answers with the production pipeline, not the answer model here."
      collapsible
      bodyId={PREFERENCES_SECTION_BODY_IDS.graphEvalModels}
    >
      <SingleModelPicker
        embedded
        labelled
        label="Eval answer model"
        hint="Model the memory-eval answer step uses to answer from recalled context. Null falls back to the knowledge answering model, then default chat. (Knowledge-track answers always use the production answering pipeline, not this.)"
        selectedId={ctrl.draft.graph.eval.answer_model}
        catalogModels={ctrl.chatOptions}
        catalogAllProviders={ctrl.catalogAllProviders}
        workspaceActiveProvidersResolved={ctrl.activeProvidersStore.resolved}
        workspaceActiveProviderIds={ctrl.activeProvidersStore.chatActiveProviderIds}
        busy={ctrl.busy}
        emptyProviders="No chat providers in catalog."
        emptyModelsForProvider="No chat models for this provider."
        onSelect={ctrl.setEvalAnswerModel}
        onChange={ctrl.markDirty}
      />
      <FormField
        label="Eval answer profile"
        hint="Tuning profile (temperature / max-tokens / thinking) for the eval answer model."
        class="max-w-md"
      >
        <select
          class={ADMIN_SELECT_LG}
          bind:value={ctrl.draft.graph.eval.answer_tuning_profile}
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
        label="Eval judge model"
        hint="Model the LLM judge uses to grade answers against the ideal (both tracks). Null falls back to the knowledge answering model, then default chat."
        selectedId={ctrl.draft.graph.eval.judge_model}
        catalogModels={ctrl.chatOptions}
        catalogAllProviders={ctrl.catalogAllProviders}
        workspaceActiveProvidersResolved={ctrl.activeProvidersStore.resolved}
        workspaceActiveProviderIds={ctrl.activeProvidersStore.chatActiveProviderIds}
        busy={ctrl.busy}
        emptyProviders="No chat providers in catalog."
        emptyModelsForProvider="No chat models for this provider."
        onSelect={ctrl.setEvalJudgeModel}
        onChange={ctrl.markDirty}
      />
      <FormField
        label="Eval judge profile"
        hint="Tuning profile for the judge model. Lower temperature = more repeatable grading."
        class="max-w-md"
      >
        <select
          class={ADMIN_SELECT_LG}
          bind:value={ctrl.draft.graph.eval.judge_tuning_profile}
          onchange={ctrl.markDirty}
        >
          {#each ctrl.profileEntries as [id, profile] (id)}
            <option value={id}>{profile.label}</option>
          {/each}
        </select>
      </FormField>
    </SectionCardMuted>

    <!-- Retrieval/ranking knobs + observability + the eval recalled-context format. -->
    <SectionCardMuted
      title="Graph search & indexing"
      description="The retrieval/ranking knobs the graph search uses, the observability tier, and the eval recalled-context format. These apply to both Agent Memory and Knowledge."
      collapsible
      bodyId={PREFERENCES_SECTION_BODY_IDS.graphEngine}
    >
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
        <FormField
          label="Query timeout (seconds)"
          hint="Hard ceiling on any single graph (Kuzu) query — writes, index rebuilds, and Graph-tab reads. Protects the server from a stuck index-rebuild checkpoint that can otherwise freeze the whole admin UI for minutes; a bounded failure is retried and logged instead. Keep above your slowest legitimate operation (index rebuilds take seconds). 0 = unlimited."
        >
          <input
            type="number"
            min="0"
            max="600"
            class={ADMIN_SELECT_LG}
            bind:value={ctrl.draft.graph.query_timeout_s}
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

      <fieldset class="grid gap-2 border-0 p-0">
        <legend class="font-sans text-sm font-medium">Eval recalled-context format</legend>
        <p class="text-xs text-muted-foreground">
          Which temporal annotations each recalled <span class="font-medium">fact</span> line carries
          in the answer + judge context — e.g.
          <code>Maya lives in Berlin [LIVES_IN · event_time: 2022-01-01]</code>. Eval-only; applied
          identically to the answer, judge, and evidence-check renders.
        </p>
        <label class="flex items-start gap-3 rounded-md border border-border/50 bg-card/45 px-3 py-2.5">
          <input
            type="checkbox"
            class="mt-0.5"
            bind:checked={ctrl.draft.graph.eval.show_event_time}
            onchange={ctrl.markDirty}
          />
          <span class="grid gap-0.5">
            <span class="font-sans text-sm font-medium">Show event_time (valid date)</span>
            <span class="font-sans text-xs text-muted-foreground">
              Adds <code>event_time: &lt;valid_at&gt;</code> to each fact. Also governs the
              <span class="font-medium">[date]</span> prefix on recalled messages (episodes).
            </span>
          </span>
        </label>
        <label class="flex items-start gap-3 rounded-md border border-border/50 bg-card/45 px-3 py-2.5">
          <input
            type="checkbox"
            class="mt-0.5"
            bind:checked={ctrl.draft.graph.eval.show_expired_at}
            onchange={ctrl.markDirty}
          />
          <span class="grid gap-0.5">
            <span class="font-sans text-sm font-medium">Show expired_at (invalid date)</span>
            <span class="font-sans text-xs text-muted-foreground">
              Adds <code>expired_at: &lt;invalid_at&gt;</code> when a fact has been invalidated —
              the upper bound of its validity window.
            </span>
          </span>
        </label>
        <label class="flex items-start gap-3 rounded-md border border-border/50 bg-card/45 px-3 py-2.5">
          <input
            type="checkbox"
            class="mt-0.5"
            bind:checked={ctrl.draft.graph.eval.show_superseded}
            onchange={ctrl.markDirty}
          />
          <span class="grid gap-0.5">
            <span class="font-sans text-sm font-medium">Show SUPERSEDED flag</span>
            <span class="font-sans text-xs text-muted-foreground">
              Tags facts that a newer fact has replaced. Only visible when the retrieval temporal
              lens is set to include historical facts.
            </span>
          </span>
        </label>
      </fieldset>
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

    <!-- Prompts, one section each. -->
    <SectionCardMuted
      title="Mem Eval Answer Prompt"
      description="Instruction block the memory-eval answer step places in the user message ahead of the question + recalled elements (the system prompt is a fixed role). Eval-only."
      collapsible
      bodyId={PREFERENCES_SECTION_BODY_IDS.graphEvalMemAnswerPrompt}
    >
      <MarkdownEditorPreview
        editorLabel="Memory eval answer prompt editor"
        previewLabel="Preview"
        ariaLabel="Memory eval answer prompt (markdown)"
        bind:value={ctrl.draft.graph.eval.memory_answer_prompt}
        defaultValue={ctrl.promptDefaults['graph.eval.memory_answer_prompt']}
        onInput={ctrl.markDirty}
      />
      <p class="text-xs text-muted-foreground">
        Drives the memory eval's <span class="font-medium">recall</span> leg. Blank uses the
        structured default (support gates, calibrator examples, absolute-date rules), declining
        with exactly "No information available." when no recalled element supports an answer —
        the abstain detector recognizes that phrase and the legacy "I don't know".
      </p>
    </SectionCardMuted>

    <SectionCardMuted
      title="Mem Eval Judge Prompt"
      description="Grading system prompt for the LLM judge that scores answers against the ideal (both tracks). Eval-only."
      collapsible
      bodyId={PREFERENCES_SECTION_BODY_IDS.graphEvalJudgePrompt}
    >
      <MarkdownEditorPreview
        editorLabel="Eval judge prompt editor"
        previewLabel="Preview"
        ariaLabel="Eval judge prompt (markdown)"
        bind:value={ctrl.draft.graph.eval.judge_prompt}
        defaultValue={ctrl.promptDefaults['graph.eval.judge_prompt']}
        onInput={ctrl.markDirty}
      />
      <p class="text-xs text-muted-foreground">
        Grades each answer against the ideal (both tracks). Blank uses the default: lenient on
        paraphrase/partial/dates, and <span class="font-medium">recall_sufficient</span> only holds
        when the judge quotes a real recalled line (verified server-side, so ungrounded "sufficient"
        claims are dropped). Verdict is always measured against the ideal. Keep the
        <span class="font-medium">Output Fields</span> section if you customize — on thinking-mode
        models the judge runs in JSON mode and that section is the only schema the model sees.
      </p>
    </SectionCardMuted>

    <SectionCardMuted
      title="Knowledge Eval Answer Prompt"
      description="The PRODUCTION Knowledge answering prompt — the knowledge eval legs run the real answering pipeline, so they are graded against this. Editing here also changes production Ask (it is the same value as Knowledge → Answering)."
      collapsible
      bodyId={PREFERENCES_SECTION_BODY_IDS.graphEvalKnowledgePrompt}
    >
      <MarkdownEditorPreview
        editorLabel="Knowledge eval answer prompt editor"
        previewLabel="Preview"
        ariaLabel="Knowledge answering prompt (markdown)"
        bind:value={ctrl.draft.knowledge.answering.prompt}
        defaultValue={ctrl.promptDefaults['knowledge.answering.prompt']}
        onInput={ctrl.markDirty}
      />
      <p class="text-xs text-muted-foreground">
        The knowledge eval legs (flat/graphiti) run the real answering pipeline, so they are graded
        against the <span class="font-medium">production</span> Knowledge answering prompt — this is
        the same value as Knowledge → Answering (editing it here changes production Ask too). Kept
        shared on purpose so the knowledge eval measures real behavior.
      </p>
    </SectionCardMuted>

    <SectionCardMuted
      title="Graph view (display)"
      description="Display-only settings for the shared Knowledge / Memories Graph tab. These tune the in-browser graph view and do not affect extraction, search, or retrieval."
      collapsible
      bodyId={PREFERENCES_SECTION_BODY_IDS.graphView}
    >
      <FormField
        label="Large node-type warning threshold"
        hint="In the Graph tab's per-type node filter, a type with more instances than this shows a 'many instances' performance heads-up in its dropdown. The dropdown still lists and searches every instance — this only flags very large types. Display-only."
        class="max-w-md"
      >
        <input
          type="number"
          min="10"
          max="10000"
          class={ADMIN_SELECT_LG}
          bind:value={ctrl.draft.graph.view.large_type_threshold}
          oninput={ctrl.markDirty}
        />
      </FormField>
    </SectionCardMuted>
  {/if}
</div>
