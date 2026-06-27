<script lang="ts">
  import Button from '$lib/components/ui/button.svelte';
  import SectionCardMuted from '$lib/components/page/SectionCardMuted.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import {
    defaultRetrievalAgentLimits,
    validateRetrievalAgentLimits
  } from '$lib/features/preferences/sections/graph-engine/retrieval-agent-limits';
  import PrefFieldGrid from '$lib/features/preferences/widgets/PrefFieldGrid.svelte';
  import PrefNumberField from '$lib/features/preferences/widgets/PrefNumberField.svelte';

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

  function restoreDefaults() {
    if (!ctrl.draft) return;
    ctrl.draft.graph.eval.retrieval_agent = defaultRetrievalAgentLimits();
    // Answer-context render caps (siblings of retrieval_agent under graph.eval).
    ctrl.draft.graph.eval.max_elements_per_kind = 30;
    ctrl.draft.graph.eval.max_fact_chars = 240;
    ctrl.draft.graph.eval.max_episode_chars = 300;
    ctrl.draft.graph.eval.max_summary_chars = 400;
    ctrl.markDirty();
  }
</script>

{#if ctrl.draft && limits}
  <SectionCardMuted
    title="Retrieval Agent"
    description="Loop-bound caps for the agentic memory-retrieval path. One global value for eval and chat — tune without hand-editing preferences.json."
    collapsible
    bodyId={PREFERENCES_SECTION_BODY_IDS.graphRetrievalAgent}
  >
    <PrefFieldGrid>
      <PrefNumberField
        {ctrl}
        path="graph.eval.retrieval_agent.max_agent_turns"
        label="Max agent turns"
        bind:value={limits.max_agent_turns}
      />
      <PrefNumberField
        {ctrl}
        path="graph.eval.retrieval_agent.max_parallel_searches"
        label="Max parallel searches"
        bind:value={limits.max_parallel_searches}
      />
      <PrefNumberField
        {ctrl}
        path="graph.eval.retrieval_agent.hops_max"
        label="Hops max"
        bind:value={limits.hops_max}
      />
      <PrefNumberField
        {ctrl}
        path="graph.eval.retrieval_agent.limit_default"
        label="Limit default"
        bind:value={limits.limit_default}
      />
      <PrefNumberField
        {ctrl}
        path="graph.eval.retrieval_agent.limit_min"
        label="Limit min"
        bind:value={limits.limit_min}
      />
      <PrefNumberField
        {ctrl}
        path="graph.eval.retrieval_agent.limit_max"
        label="Limit max"
        bind:value={limits.limit_max}
      />
    </PrefFieldGrid>

    {#if evalPrefs}
      <p class="text-xs font-medium text-muted-foreground">
        Answer context — caps the recalled set handed to the answerer + judge (score-ranked top-N
        per kind, each element sanitized to one capped line).
      </p>
      <PrefFieldGrid>
        <PrefNumberField
          {ctrl}
          path="graph.eval.max_elements_per_kind"
          label="Max elements / kind"
          bind:value={evalPrefs.max_elements_per_kind}
        />
        <PrefNumberField
          {ctrl}
          path="graph.eval.max_fact_chars"
          label="Max fact chars"
          bind:value={evalPrefs.max_fact_chars}
        />
        <PrefNumberField
          {ctrl}
          path="graph.eval.max_episode_chars"
          label="Max message chars"
          bind:value={evalPrefs.max_episode_chars}
        />
        <PrefNumberField
          {ctrl}
          path="graph.eval.max_summary_chars"
          label="Max entity summary chars"
          bind:value={evalPrefs.max_summary_chars}
        />
      </PrefFieldGrid>
    {/if}

    {#if validationError}
      <p class="text-xs text-destructive">{validationError}</p>
    {/if}

    <div class="flex flex-wrap gap-2">
      <Button variant="outline" size="sm" onclick={restoreDefaults}>Restore defaults</Button>
    </div>
  </SectionCardMuted>
{/if}
