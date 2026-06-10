<!--
  Confirm dialog shown when "Run" is clicked with a graph-WIPING option checked on a corpus that
  ALREADY has a graph — memory "Clear graph first", or knowledge "Rebuild graph" (which wipes on
  re-ingest). The wipe is destructive and costs LLM + embedder to rebuild, so it's gated behind an
  explicit confirm. Mirrors KnowledgeBrowseRemoveGraphDialog (bits-ui Dialog + destructive confirm).
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

  const isMemory = $derived(track === 'memory');
  const what = $derived(isMemory ? 'memory graph' : 'entity graph');
  // The checkbox that triggered this confirm — its label + the verb differ per track.
  const toggle = $derived(isMemory ? 'Clear Graph' : 'Rebuild graph');
  const verb = $derived(isMemory ? 'Clear' : 'Rebuild');
</script>

<Dialog.Root bind:open>
  <Dialog.Content class="sm:max-w-lg">
    <Dialog.Header>
      <Dialog.Title class="break-words">{verb} graph for “{corpusName}”?</Dialog.Title>
      <Dialog.Description>
        This corpus already has a {what}. Running with “{toggle}” on will
        <strong>wipe the existing graph</strong> before {isMemory ? 'ingesting' : 'rebuilding'} —
        incurring LLM and embedder cost to rebuild. {isMemory
          ? 'To APPEND another batch to the existing graph instead, cancel and uncheck “Clear Graph”.'
          : 'To reuse the existing graph instead, cancel and uncheck “Rebuild graph”.'}
      </Dialog.Description>
    </Dialog.Header>

    <Dialog.Footer>
      <Button variant="outline" onclick={() => (open = false)}>Cancel</Button>
      <Button variant="destructive" onclick={() => onConfirm()}>{verb} &amp; run</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
