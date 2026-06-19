<script lang="ts">
  import MarkdownEditorPreview from '$lib/components/ui/markdown/MarkdownEditorPreview.svelte';
  import SectionCardMuted from '$lib/components/page/SectionCardMuted.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();
</script>

{#if ctrl.draft}
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
{/if}
