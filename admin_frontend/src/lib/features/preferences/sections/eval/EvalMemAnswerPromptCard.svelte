<script lang="ts">
  import SectionCardMuted from '$lib/components/page/SectionCardMuted.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import PromptLibraryField from '$lib/features/preferences/widgets/prompts/PromptLibraryField.svelte';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();
</script>

{#if ctrl.draft}
  <SectionCardMuted
    title="Mem Eval Answer Prompts"
    description="A library of named instruction blocks the memory-eval answer step can use (the system prompt is a fixed role). A run picks one in the eval panel. Eval-only; memory track only."
    collapsible
    bodyId={PREFERENCES_SECTION_BODY_IDS.evalMemAnswerPrompt}
  >
    <PromptLibraryField
      {ctrl}
      dictPath="graph.eval.answer_prompts"
      label="Mem Eval Answer Prompts"
      hint={'Drives the memory eval\'s recall leg. Each profile should keep declining with exactly "No information available." when no recalled element supports an answer — the abstain detector recognizes that phrase (and the legacy "I don\'t know"). The locked default carries the structured default (support gates, calibrator examples, absolute-date rules); duplicate it to customize.'}
      ariaLabel="Mem-eval answer prompt (markdown)"
      editorLabel="Answer prompt editor"
    />
  </SectionCardMuted>
{/if}
