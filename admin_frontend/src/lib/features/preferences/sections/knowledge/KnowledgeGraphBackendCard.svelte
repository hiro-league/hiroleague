<script lang="ts">
  import FormField from '$lib/components/ui/form-field.svelte';
  import SectionCardMuted from '$lib/components/page/SectionCardMuted.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { KNOWLEDGE_COPY } from '$lib/features/preferences/shared/preferences-copy';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import { ADMIN_SELECT_LG } from '$lib/features/preferences/shared/preferences-ui';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();
</script>

{#if ctrl.draft}
  <SectionCardMuted
    title="Knowledge graph retrieval"
    description="Whether knowledge answering uses the temporal graph. Off = flat Qdrant retrieval only. Graphiti = answer from the graph's facts and their supporting passages (recommended for relational + temporal questions). Build the graph from a document on the Add tab first."
    collapsible
    bodyId={PREFERENCES_SECTION_BODY_IDS.knowledgeGraphBackend}
  >
    <FormField
      label="Graph backend"
      hint={KNOWLEDGE_COPY.graphBackend}
      class="max-w-md"
    >
      <select
        class={ADMIN_SELECT_LG}
        bind:value={ctrl.draft.graph.backend}
        onchange={ctrl.markDirty}
      >
        <option value="off">Off — flat Qdrant only</option>
        <option value="graphiti">Graphiti — graph facts (recommended)</option>
      </select>
    </FormField>
    <p class="text-xs text-muted-foreground">
      The graph engine itself — extraction/small models, embedder, search recipe, and reranker —
      is shared with Agent Memory and configured in the <span class="font-medium">Graph Engine</span>
      tab.
    </p>
  </SectionCardMuted>
{/if}
