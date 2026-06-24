<!--
  Confirm dialog shown when "Clear results" is clicked on the MEMORY track. Memory clear calls
  clearEvalResults() which PERMANENTLY deletes the corpus's saved eval results from disk (ingested
  memory is kept) — an irreversible, accidentally-easy-to-trigger action, so it is gated behind an
  explicit confirm. The knowledge track's "Clear" only resets the in-view run state (non-destructive)
  and is NOT gated.
-->
<script lang="ts">
  import ConfirmDialog from '$lib/components/ui/dialog/ConfirmDialog.svelte';
  import * as Dialog from '$lib/components/ui/dialog';

  type Props = {
    open: boolean;
    corpusName: string;
    savedCount: number;
    onOpenChange: (open: boolean) => void; // required — forwarded to ConfirmDialog's dismissal handler
    onConfirm: () => void;
  };

  let { open, corpusName, savedCount, onOpenChange, onConfirm }: Props = $props();

  const countLabel = $derived(
    savedCount > 0 ? `${savedCount} saved question result${savedCount === 1 ? '' : 's'}` : 'the saved results'
  );
</script>

<ConfirmDialog
  {open}
  {onOpenChange}
  title={`Clear saved results for “${corpusName}”?`}
  confirmLabel="Clear results"
  widthClass="sm:max-w-lg"
  {onConfirm}
>
  {#snippet description()}
    <Dialog.Description>
      This <strong>permanently deletes {countLabel}</strong> for this corpus from disk and
      <strong>cannot be undone</strong>. All <strong>Report data and Answer Details</strong> for
      this corpus will be wiped. Ingested memory (the graph) is kept, so you can re-run the eval
      without re-ingesting.
    </Dialog.Description>
  {/snippet}
</ConfirmDialog>
