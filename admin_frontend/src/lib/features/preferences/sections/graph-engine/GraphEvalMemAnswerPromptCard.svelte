<script lang="ts">
  import MarkdownEditorPreview from '$lib/components/ui/markdown/MarkdownEditorPreview.svelte';
  import SectionCardMuted from '$lib/components/page/SectionCardMuted.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import EvalAnswerPromptLibrary from '$lib/features/preferences/widgets/EvalAnswerPromptLibrary.svelte';

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
    bodyId={PREFERENCES_SECTION_BODY_IDS.graphEvalMemAnswerPrompt}
  >
    <EvalAnswerPromptLibrary {ctrl} />
    <p class="text-xs text-muted-foreground">
      Drives the memory eval's <span class="font-medium">recall</span> leg. Each profile should
      keep declining with exactly "No information available." when no recalled element supports an
      answer — the abstain detector recognizes that phrase (and the legacy "I don't know"). The
      locked default carries the structured default (support gates, calibrator examples,
      absolute-date rules); duplicate it to customize.
    </p>
  </SectionCardMuted>
{/if}
