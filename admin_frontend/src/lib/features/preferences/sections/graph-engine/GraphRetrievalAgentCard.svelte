<script lang="ts">
  import PrefSectionCard from '$lib/features/preferences/widgets/PrefSectionCard.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import { validateRetrievalAgentLimits } from '$lib/features/preferences/sections/graph-engine/retrieval-agent-limits';
  import PrefFieldGrid from '$lib/features/preferences/widgets/PrefFieldGrid.svelte';
  import PrefNumberField from '$lib/features/preferences/widgets/PrefNumberField.svelte';
  import PrefPanel from '$lib/features/preferences/widgets/PrefPanel.svelte';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();

  const limits = $derived(ctrl.draft?.graph.eval.retrieval_agent);
  const evalPrefs = $derived(ctrl.draft?.graph.eval);
  const validationError = $derived(limits ? validateRetrievalAgentLimits(limits) : null);

  $effect(() => {
    ctrl.setSectionError('retrieval_agent', validationError);
  });
  // Per-group "restore defaults" now lives on each PrefPanel (group reset off the effective-defaults
  // tree), replacing the old card-wide button that hardcoded the answer-context cap literals.
</script>

{#if ctrl.draft && limits}
  <PrefSectionCard
    title="Retrieval Agent"
    description="Loop-bound caps for the agentic memory-retrieval path. One global value for eval and chat — tune without hand-editing preferences.json."
    collapsible
    bodyId={PREFERENCES_SECTION_BODY_IDS.graphRetrievalAgent}
  >
    <PrefPanel {ctrl} title="Loop limits">
      <PrefFieldGrid>
        <PrefNumberField
          {ctrl}
          path="graph.eval.retrieval_agent.max_agent_turns"
        />
        <PrefNumberField
          {ctrl}
          path="graph.eval.retrieval_agent.max_parallel_searches"
        />
        <PrefNumberField
          {ctrl}
          path="graph.eval.retrieval_agent.hops_max"
        />
        <PrefNumberField
          {ctrl}
          path="graph.eval.retrieval_agent.limit_default"
        />
        <PrefNumberField
          {ctrl}
          path="graph.eval.retrieval_agent.limit_min"
        />
        <PrefNumberField
          {ctrl}
          path="graph.eval.retrieval_agent.limit_max"
        />
      </PrefFieldGrid>
    </PrefPanel>

    {#if evalPrefs}
      <PrefPanel
        {ctrl}
        title="Answer context"
        hint="Caps the recalled set handed to the answerer + judge — score-ranked top-N per kind, each element sanitized to one capped line."
      >
        <PrefFieldGrid>
          <PrefNumberField
            {ctrl}
            path="graph.eval.max_elements_per_kind"
          />
          <PrefNumberField
            {ctrl}
            path="graph.eval.max_fact_chars"
          />
          <PrefNumberField
            {ctrl}
            path="graph.eval.max_episode_chars"
          />
          <PrefNumberField
            {ctrl}
            path="graph.eval.max_summary_chars"
          />
        </PrefFieldGrid>
      </PrefPanel>
    {/if}

    {#if validationError}
      <p class="text-xs text-destructive">{validationError}</p>
    {/if}
  </PrefSectionCard>
{/if}
