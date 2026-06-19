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
{/if}
