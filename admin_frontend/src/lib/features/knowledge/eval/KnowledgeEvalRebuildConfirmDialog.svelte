<!--
  Confirm dialog shown when "Run eval" is clicked with "Rebuild graph" checked on a
  corpus that ALREADY has a graph. Rebuilding wipes the existing graph and re-ingests
  from scratch (LLM + embedder cost), so the run is gated behind an explicit confirm.
  Mirrors KnowledgeBrowseRemoveGraphDialog (bits-ui Dialog + destructive confirm).
-->
<script lang="ts">
  import Button from '$lib/components/ui/button.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import type { EvalTrack } from '$lib/features/knowledge/state/knowledge-eval.svelte';

  type Props = {
    open: boolean;
    track: EvalTrack;
    corpusName: string;
    onConfirm: () => void;
  };

  let { open = $bindable(false), track, corpusName, onConfirm }: Props = $props();

  // Memory rebuilds re-remember the turn corpus; knowledge rebuilds re-ingest the entity graph.
  const what = $derived(track === 'memory' ? 'memory graph' : 'entity graph');
</script>

<Dialog.Root bind:open>
  <Dialog.Content class="sm:max-w-lg">
    <Dialog.Header>
      <Dialog.Title class="break-words">Rebuild graph for “{corpusName}”?</Dialog.Title>
      <Dialog.Description>
        This corpus already has a {what}. Running with “Rebuild graph” on will
        <strong>wipe the existing graph</strong> and rebuild it from scratch — incurring LLM and
        embedder cost. To reuse the existing graph instead, cancel and uncheck “Rebuild graph”.
      </Dialog.Description>
    </Dialog.Header>

    <Dialog.Footer>
      <Button variant="outline" onclick={() => (open = false)}>Cancel</Button>
      <Button variant="destructive" onclick={() => onConfirm()}>Rebuild &amp; run</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
