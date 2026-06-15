<!--
  Confirm dialog shown when "Clear results" is clicked on the MEMORY track. Memory clear calls
  clearEvalResults() which PERMANENTLY deletes the corpus's saved eval results from disk (ingested
  memory is kept) — an irreversible, accidentally-easy-to-trigger action, so it is gated behind an
  explicit confirm. The knowledge track's "Clear" only resets the in-view run state (non-destructive)
  and is NOT gated. Mirrors KnowledgeEvalRebuildConfirmDialog (bits-ui Dialog + destructive confirm).
-->
<script lang="ts">
  import Button from '$lib/components/ui/button.svelte';
  import * as Dialog from '$lib/components/ui/dialog';

  type Props = {
    open: boolean;
    corpusName: string;
    savedCount: number;
    onConfirm: () => void;
  };

  let { open = $bindable(false), corpusName, savedCount, onConfirm }: Props = $props();

  const countLabel = $derived(
    savedCount > 0 ? `${savedCount} saved question result${savedCount === 1 ? '' : 's'}` : 'the saved results'
  );
</script>

<Dialog.Root bind:open>
  <Dialog.Content class="sm:max-w-lg">
    <Dialog.Header>
      <Dialog.Title class="break-words">Clear saved results for “{corpusName}”?</Dialog.Title>
      <Dialog.Description>
        This <strong>permanently deletes {countLabel}</strong> for this corpus from disk and
        <strong>cannot be undone</strong>. Ingested memory (the graph) is kept, so you can re-run the
        eval without re-ingesting.
      </Dialog.Description>
    </Dialog.Header>

    <Dialog.Footer>
      <Button variant="outline" onclick={() => (open = false)}>Cancel</Button>
      <Button variant="destructive" onclick={() => onConfirm()}>Clear results</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
