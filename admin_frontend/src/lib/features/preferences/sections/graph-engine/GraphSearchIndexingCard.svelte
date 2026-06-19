<script lang="ts">
  import FormField from '$lib/components/ui/form-field.svelte';
  import SectionCardMuted from '$lib/components/page/SectionCardMuted.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import { GRAPH_SEARCH_INDEXING_COPY } from '$lib/features/preferences/shared/preferences-copy';
  import { ADMIN_SELECT_LG } from '$lib/features/preferences/shared/preferences-ui';
  import SettingToggle from '$lib/features/preferences/widgets/SettingToggle.svelte';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();
</script>

{#if ctrl.draft}
  <SectionCardMuted
    title="Graph search & indexing"
    description="The retrieval/ranking knobs the graph search uses, the observability tier, and the eval recalled-context format. These apply to both Agent Memory and Knowledge."
    collapsible
    bodyId={PREFERENCES_SECTION_BODY_IDS.graphEngine}
  >
    <div class="grid gap-3 md:grid-cols-2">
      <FormField
        label="Temporal lens (default)"
        hint={GRAPH_SEARCH_INDEXING_COPY.temporalDefault}
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
        hint={GRAPH_SEARCH_INDEXING_COPY.kHop}
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
        hint={GRAPH_SEARCH_INDEXING_COPY.searchRecipe}
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
        hint={GRAPH_SEARCH_INDEXING_COPY.searchScope}
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
        hint={GRAPH_SEARCH_INDEXING_COPY.simMinScore}
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
        hint={GRAPH_SEARCH_INDEXING_COPY.queryTimeout}
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
      hint={GRAPH_SEARCH_INDEXING_COPY.observability}
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
      <SettingToggle
        label="Show event_time (valid date)"
        bind:checked={ctrl.draft.graph.eval.show_event_time}
        onchange={ctrl.markDirty}
      >
        {#snippet details()}
          Adds <code>event_time: &lt;valid_at&gt;</code> to each fact. Also governs the
          <span class="font-medium">[date]</span> prefix on recalled messages (episodes).
        {/snippet}
      </SettingToggle>
      <SettingToggle
        label="Show expired_at (invalid date)"
        bind:checked={ctrl.draft.graph.eval.show_expired_at}
        onchange={ctrl.markDirty}
      >
        {#snippet details()}
          Adds <code>expired_at: &lt;invalid_at&gt;</code> when a fact has been invalidated —
          the upper bound of its validity window.
        {/snippet}
      </SettingToggle>
      <SettingToggle
        label="Show SUPERSEDED flag"
        bind:checked={ctrl.draft.graph.eval.show_superseded}
        onchange={ctrl.markDirty}
      >
        {#snippet details()}
          Tags facts that a newer fact has replaced. Only visible when the retrieval temporal
          lens is set to include historical facts.
        {/snippet}
      </SettingToggle>
    </fieldset>
  </SectionCardMuted>
{/if}
