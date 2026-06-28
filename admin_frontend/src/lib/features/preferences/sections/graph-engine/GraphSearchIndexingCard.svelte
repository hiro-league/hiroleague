<script lang="ts">
  import PrefSectionCard from '$lib/features/preferences/widgets/PrefSectionCard.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import type { PrefSelectOption } from '$lib/features/preferences/shared/preferences-field-options';
  import {
    GRAPH_OBSERVABILITY_LABELS,
    GRAPH_SEARCH_RECIPE_LABELS,
    GRAPH_SEARCH_SCOPE_LABELS,
    GRAPH_TEMPORAL_DEFAULT_LABELS
  } from '$lib/features/preferences/shared/preferences-enum-labels';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import PrefFieldGrid from '$lib/features/preferences/widgets/PrefFieldGrid.svelte';
  import PrefNumberField from '$lib/features/preferences/widgets/PrefNumberField.svelte';
  import PrefSelectField from '$lib/features/preferences/widgets/PrefSelectField.svelte';
  import PrefToggleField from '$lib/features/preferences/widgets/PrefToggleField.svelte';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();

  // Both episodes-inclusive scopes mount the BM25-only episodes leg, which has no MMR reranker —
  // mirror the backend's KNOWLEDGE_GRAPH_EPISODE_SCOPES gate so the UI disables MMR for either.
  const episodesInScope = $derived(
    ctrl.draft?.graph.search_scope === 'edges_and_episodes' ||
      ctrl.draft?.graph.search_scope === 'edges_nodes_episodes'
  );

  const searchRecipeOptions = $derived.by((): PrefSelectOption[] => {
    const mmrDisabled = episodesInScope;
    return [
      { value: 'rrf', label: GRAPH_SEARCH_RECIPE_LABELS.rrf },
      {
        value: 'mmr',
        label: `${GRAPH_SEARCH_RECIPE_LABELS.mmr}${mmrDisabled ? ' (n/a with episodes)' : ''}`,
        disabled: mmrDisabled,
        title: mmrDisabled
          ? 'MMR is not supported when scope includes episodes (episodes are BM25-only and EpisodeReranker has no MMR). Switch scope, or pick RRF / Cross-encoder.'
          : undefined
      },
      { value: 'cross_encoder', label: GRAPH_SEARCH_RECIPE_LABELS.cross_encoder }
    ];
  });

  const searchScopeOptions = $derived.by((): PrefSelectOption[] => {
    const mmrRecipe = ctrl.draft?.graph.search_recipe === 'mmr';
    const episodesDisabledTitle =
      'Episodes leg is BM25-only and EpisodeReranker has no MMR. Switch recipe to RRF or Cross-encoder, then select this scope.';
    return [
      { value: 'edges', label: GRAPH_SEARCH_SCOPE_LABELS.edges },
      { value: 'edges_and_nodes', label: GRAPH_SEARCH_SCOPE_LABELS.edges_and_nodes },
      {
        value: 'edges_and_episodes',
        label: `${GRAPH_SEARCH_SCOPE_LABELS.edges_and_episodes}${mmrRecipe ? ' (n/a with MMR)' : ''}`,
        disabled: mmrRecipe,
        title: mmrRecipe ? episodesDisabledTitle : undefined
      },
      {
        value: 'edges_nodes_episodes',
        label: `${GRAPH_SEARCH_SCOPE_LABELS.edges_nodes_episodes}${mmrRecipe ? ' (n/a with MMR)' : ''}`,
        disabled: mmrRecipe,
        title: mmrRecipe ? episodesDisabledTitle : undefined
      }
    ];
  });
</script>

{#if ctrl.draft}
  <PrefSectionCard
    title="Graph search & indexing"
    description="The retrieval/ranking knobs the graph search uses, the observability tier, and the eval recalled-context format. These apply to both Agent Memory and Knowledge."
    collapsible
    bodyId={PREFERENCES_SECTION_BODY_IDS.graphEngine}
  >
    <PrefFieldGrid>
      <PrefSelectField
        {ctrl}
        path="graph.temporal_default"
        label="Temporal lens (default)"
        options={GRAPH_TEMPORAL_DEFAULT_LABELS}
        bind:value={ctrl.draft.graph.temporal_default}
      />
      <PrefNumberField
        {ctrl}
        path="graph.k_hop"
        label="Expansion hops (k)"
        bind:value={ctrl.draft.graph.k_hop}
      />
      <PrefSelectField
        {ctrl}
        path="graph.search_recipe"
        label="Search recipe"
        options={searchRecipeOptions}
        bind:value={ctrl.draft.graph.search_recipe}
      />
      <PrefSelectField
        {ctrl}
        path="graph.search_scope"
        label="Search scope"
        options={searchScopeOptions}
        bind:value={ctrl.draft.graph.search_scope}
      />
      <PrefNumberField
        {ctrl}
        path="graph.sim_min_score"
        label="Candidate similarity floor"
        bind:value={ctrl.draft.graph.sim_min_score}
      />
      <PrefNumberField
        {ctrl}
        path="graph.query_timeout_s"
        label="Query timeout (seconds)"
        bind:value={ctrl.draft.graph.query_timeout_s}
      />
      <PrefSelectField
        {ctrl}
        path="graph.observability"
        label="Graph observability"
        options={GRAPH_OBSERVABILITY_LABELS}
        bind:value={ctrl.draft.graph.observability}
      />
    </PrefFieldGrid>

    <fieldset class="grid gap-2 border-0 p-0">
      <legend class="font-sans text-sm font-medium">Eval recalled-context format</legend>
      <p class="text-xs text-muted-foreground">
        Which temporal annotations each recalled <span class="font-medium">fact</span> line carries
        in the answer + judge context — e.g.
        <code>Maya lives in Berlin [LIVES_IN · event_time: 2022-01-01]</code>. Eval-only; applied
        identically to the answer, judge, and evidence-check renders.
      </p>
      <PrefFieldGrid>
        <PrefToggleField
          {ctrl}
          path="graph.eval.show_event_time"
          label="Show event_time (valid date)"
          hint="Adds 'event_time: <valid_at>' to each fact. Also governs the [date] prefix on recalled messages (episodes)."
          bind:checked={ctrl.draft.graph.eval.show_event_time}
        />
        <PrefToggleField
          {ctrl}
          path="graph.eval.show_expired_at"
          label="Show expired_at (invalid date)"
          hint="Adds 'expired_at: <invalid_at>' when a fact has been invalidated — the upper bound of its validity window."
          bind:checked={ctrl.draft.graph.eval.show_expired_at}
        />
        <PrefToggleField
          {ctrl}
          path="graph.eval.show_superseded"
          label="Show SUPERSEDED flag"
          hint="Tags facts that a newer fact has replaced. Only visible when the retrieval temporal lens is set to include historical facts."
          bind:checked={ctrl.draft.graph.eval.show_superseded}
        />
      </PrefFieldGrid>
    </fieldset>
  </PrefSectionCard>
{/if}
