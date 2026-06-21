<script lang="ts">
  import FormField from '$lib/components/ui/form-field.svelte';
  import SectionCardMuted from '$lib/components/page/SectionCardMuted.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import { ADMIN_SELECT_LG } from '$lib/features/preferences/shared/preferences-ui';
  import EvalRetrievalAgentPromptLibrary from '$lib/features/preferences/widgets/EvalRetrievalAgentPromptLibrary.svelte';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();

  const activePromptEntries = $derived(
    Object.entries(ctrl.draft?.graph.eval.retrieval_agent_prompts ?? {}).sort(([ka, a], [kb, b]) =>
      ka === 'default' ? -1 : kb === 'default' ? 1 : a.label.localeCompare(b.label)
    )
  );
</script>

{#if ctrl.draft}
  <SectionCardMuted
    title="Mem Eval Retrieval Agent Prompt"
    description="System prompt library for the agentic memory-retrieval loop. Eval-only; blank custom text falls back to the built-in default at runtime."
    collapsible
    bodyId={PREFERENCES_SECTION_BODY_IDS.graphEvalRetrievalAgentPrompt}
  >
    <FormField
      label="Active prompt profile"
      class="max-w-md"
      hint="Which retrieval-agent system prompt the loop uses."
    >
      <select
        class={ADMIN_SELECT_LG}
        bind:value={ctrl.draft.graph.eval.active_retrieval_agent_prompt_id}
        onchange={ctrl.markDirty}
      >
        {#each activePromptEntries as [id, profile] (id)}
          <option value={id}>{profile.label}{profile.locked ? ' 🔒' : ''}</option>
        {/each}
      </select>
    </FormField>

    <EvalRetrievalAgentPromptLibrary {ctrl} />

    <p class="text-xs text-muted-foreground">
      Drives the memory eval's <span class="font-medium">recall</span> leg. Placeholders
      <span class="font-medium">{`{MAX_AGENT_TURNS}`}</span>,
      <span class="font-medium">{`{MAX_PARALLEL_SEARCHES}`}</span>, and
      <span class="font-medium">{`{MAX_LIMIT}`}</span> are filled from the
      <span class="font-medium">Retrieval Agent</span> caps card at runtime.
    </p>
  </SectionCardMuted>
{/if}
