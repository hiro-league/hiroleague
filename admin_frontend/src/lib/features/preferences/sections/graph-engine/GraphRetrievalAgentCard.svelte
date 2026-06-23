<script lang="ts">
  import Button from '$lib/components/ui/button.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import SectionCardMuted from '$lib/components/page/SectionCardMuted.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import { ADMIN_SELECT_LG } from '$lib/features/preferences/shared/preferences-ui';
  import {
    defaultRetrievalAgentLimits,
    RETRIEVAL_AGENT_LIMIT_BOUNDS,
    validateRetrievalAgentLimits
  } from '$lib/features/preferences/sections/graph-engine/retrieval-agent-limits';

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
    <div class="grid gap-3 md:grid-cols-3">
      <FormField
        label="Max agent turns"
        hint="How many LLM turns the agent gets across the whole loop (includes the final-answer turn). Each search turn may emit up to max parallel searches sub-queries in one tool call."
      >
        <input
          type="number"
          min={RETRIEVAL_AGENT_LIMIT_BOUNDS.max_agent_turns.min}
          max={RETRIEVAL_AGENT_LIMIT_BOUNDS.max_agent_turns.max}
          class={ADMIN_SELECT_LG}
          bind:value={limits.max_agent_turns}
          oninput={ctrl.markDirty}
        />
      </FormField>
      <FormField
        label="Max parallel searches"
        hint="Sub-queries per search_memory call — global for eval and chat."
      >
        <input
          type="number"
          min={RETRIEVAL_AGENT_LIMIT_BOUNDS.max_parallel_searches.min}
          max={RETRIEVAL_AGENT_LIMIT_BOUNDS.max_parallel_searches.max}
          class={ADMIN_SELECT_LG}
          bind:value={limits.max_parallel_searches}
          oninput={ctrl.markDirty}
        />
      </FormField>
      <FormField label="Hops max" hint="Upper bound the tool accepts per search (1–3).">
        <input
          type="number"
          min={RETRIEVAL_AGENT_LIMIT_BOUNDS.hops_max.min}
          max={RETRIEVAL_AGENT_LIMIT_BOUNDS.hops_max.max}
          class={ADMIN_SELECT_LG}
          bind:value={limits.hops_max}
          oninput={ctrl.markDirty}
        />
      </FormField>
    </div>
    <div class="grid gap-3 md:grid-cols-3">
      <FormField label="Limit default" hint="Starting num_results per search_memory call.">
        <input
          type="number"
          min={RETRIEVAL_AGENT_LIMIT_BOUNDS.limit_default.min}
          max={RETRIEVAL_AGENT_LIMIT_BOUNDS.limit_default.max}
          class={ADMIN_SELECT_LG}
          bind:value={limits.limit_default}
          oninput={ctrl.markDirty}
        />
      </FormField>
      <FormField label="Limit min" hint="Soft floor when the tool clamps limit.">
        <input
          type="number"
          min={RETRIEVAL_AGENT_LIMIT_BOUNDS.limit_min.min}
          max={RETRIEVAL_AGENT_LIMIT_BOUNDS.limit_min.max}
          class={ADMIN_SELECT_LG}
          bind:value={limits.limit_min}
          oninput={ctrl.markDirty}
        />
      </FormField>
      <FormField label="Limit max" hint="Soft ceiling when the tool clamps limit.">
        <input
          type="number"
          min={RETRIEVAL_AGENT_LIMIT_BOUNDS.limit_max.min}
          max={RETRIEVAL_AGENT_LIMIT_BOUNDS.limit_max.max}
          class={ADMIN_SELECT_LG}
          bind:value={limits.limit_max}
          oninput={ctrl.markDirty}
        />
      </FormField>
    </div>

    {#if evalPrefs}
      <p class="text-xs font-medium text-muted-foreground">
        Answer context — caps the recalled set handed to the answerer + judge (score-ranked top-N
        per kind, each element sanitized to one capped line).
      </p>
      <div class="grid gap-3 md:grid-cols-2">
        <FormField
          label="Max elements / kind"
          hint="Top-N facts / entities / messages (by retrieval score) kept for the answer + judge prompts, so the answer-relevant ones aren't buried under a long dump."
        >
          <input
            type="number"
            min={1}
            max={200}
            class={ADMIN_SELECT_LG}
            bind:value={evalPrefs.max_elements_per_kind}
            oninput={ctrl.markDirty}
          />
        </FormField>
        <FormField label="Max fact chars" hint="Each recalled fact → one sanitized line capped here.">
          <input
            type="number"
            min={40}
            max={2000}
            class={ADMIN_SELECT_LG}
            bind:value={evalPrefs.max_fact_chars}
            oninput={ctrl.markDirty}
          />
        </FormField>
        <FormField label="Max message chars" hint="Per-episode/message text cap (one sanitized line).">
          <input
            type="number"
            min={40}
            max={2000}
            class={ADMIN_SELECT_LG}
            bind:value={evalPrefs.max_episode_chars}
            oninput={ctrl.markDirty}
          />
        </FormField>
        <FormField
          label="Max entity summary chars"
          hint="Per-entity summary cap (one sanitized line) — entity summaries are the longest/noisiest."
        >
          <input
            type="number"
            min={40}
            max={4000}
            class={ADMIN_SELECT_LG}
            bind:value={evalPrefs.max_summary_chars}
            oninput={ctrl.markDirty}
          />
        </FormField>
      </div>
    {/if}

    {#if validationError}
      <p class="text-xs text-destructive">{validationError}</p>
    {/if}

    <div class="flex flex-wrap gap-2">
      <Button variant="outline" size="sm" onclick={restoreDefaults}>Restore defaults</Button>
    </div>
  </SectionCardMuted>
{/if}
