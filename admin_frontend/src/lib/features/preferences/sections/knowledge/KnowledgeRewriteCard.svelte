<script lang="ts">
  import PromptField from '$lib/features/preferences/widgets/prompts/PromptField.svelte';
  import SectionCardMuted from '$lib/components/page/SectionCardMuted.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import PrefToggleField from '$lib/features/preferences/widgets/PrefToggleField.svelte';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();
</script>

{#if ctrl.draft}
  <SectionCardMuted
    title="Query Rewrite (Ask Tab/Chat Agent)"
    description="Optional LLM step that rewrites a question before retrieval — normalizes wording and extracts literal keywords. Reuses the answering model; toggled per query on the Ask tab."
    collapsible
    bodyId={PREFERENCES_SECTION_BODY_IDS.knowledgeRewrite}
  >
    <PrefToggleField
      {ctrl}
      path="knowledge.rewrite.default_on"
      label="Enable by default on the Ask tab"
      bind:checked={ctrl.draft.knowledge.rewrite.default_on}
    />
    <PromptField
      {ctrl}
      path="knowledge.rewrite.prompt"
      label="Rewrite prompt"
      hint="Sent as the system prompt for the rewrite call. Keep the instruction to copy proper nouns and identifiers verbatim so the BM25 keyword branch keeps its exact-match signal."
      ariaLabel="Knowledge query rewrite prompt (markdown)"
      editorLabel="Rewrite prompt editor"
    />
  </SectionCardMuted>
{/if}
