<script lang="ts">
  import SectionCardMuted from '$lib/components/page/SectionCardMuted.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { GRAPH_BACKEND_LABELS } from '$lib/features/preferences/shared/preferences-enum-labels';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import PrefSelectField from '$lib/features/preferences/widgets/PrefSelectField.svelte';

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
    <PrefSelectField
      {ctrl}
      path="graph.backend"
      label="Graph backend"
      hint="Master switch for knowledge retrieval. Off = today's flat Qdrant retrieval (graph untouched). Graphiti = answer from the graph's facts."
      options={GRAPH_BACKEND_LABELS}
      class="max-w-md"
      bind:value={ctrl.draft.graph.backend}
    />
    <p class="text-xs text-muted-foreground">
      The graph engine itself — extraction/small models, embedder, search recipe, and reranker —
      is shared with Agent Memory and configured in the <span class="font-medium">Graph Engine</span>
      tab.
    </p>
  </SectionCardMuted>
{/if}
