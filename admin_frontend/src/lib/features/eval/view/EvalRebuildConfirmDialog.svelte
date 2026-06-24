<!--
  Confirm dialog shown when "Run" is clicked with a graph-WIPING option checked on a corpus that
  ALREADY has a graph — memory "Clear graph first", or knowledge "Rebuild graph" (which wipes on
  re-ingest). The wipe is destructive and costs LLM + embedder to rebuild, so it's gated behind an
  explicit confirm.
-->
<script lang="ts">
  import ConfirmDialog from '$lib/components/ui/dialog/ConfirmDialog.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import type { EvalTrack } from '$lib/features/eval/state/eval-model.svelte';

  type Props = {
    open: boolean;
    track: EvalTrack;
    corpusName: string;
    onOpenChange: (open: boolean) => void; // required — forwarded to ConfirmDialog's dismissal handler
    onConfirm: () => void;
  };

  let { open, track, corpusName, onOpenChange, onConfirm }: Props = $props();

  const isMemory = $derived(track === 'memory');
  const what = $derived(isMemory ? 'memory graph' : 'entity graph');
  const toggle = $derived(isMemory ? 'Clear Graph' : 'Rebuild graph');
  const verb = $derived(isMemory ? 'Clear' : 'Rebuild');
</script>

<ConfirmDialog
  {open}
  {onOpenChange}
  title={`${verb} graph for “${corpusName}”?`}
  confirmLabel={`${verb} & run`}
  widthClass="sm:max-w-lg"
  {onConfirm}
>
  {#snippet description()}
    <Dialog.Description>
      This corpus already has a {what}. Running with “{toggle}” on will
      <strong>wipe the existing graph</strong> before {isMemory ? 'ingesting' : 'rebuilding'} —
      incurring LLM and embedder cost to rebuild. {isMemory
        ? 'To APPEND another batch to the existing graph instead, cancel and uncheck “Clear Graph”.'
        : 'To reuse the existing graph instead, cancel and uncheck “Rebuild graph”.'}
    </Dialog.Description>
  {/snippet}
</ConfirmDialog>
