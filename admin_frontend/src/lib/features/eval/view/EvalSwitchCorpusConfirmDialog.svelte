<!--
  Confirm dialog when switching corpus on the KNOWLEDGE track while a completed/failed run's
  in-view results would be discarded (memory track persists per corpus, so no prompt there).
  Mirrors EvalClearResultsConfirmDialog.
-->
<script lang="ts">
  import Button from '$lib/components/ui/button.svelte';
  import * as Dialog from '$lib/components/ui/dialog';

  type Props = {
    open: boolean;
    corpusName: string;
    onOpenChange: (open: boolean) => void;
    onConfirm: () => void;
  };

  let { open, corpusName, onOpenChange, onConfirm }: Props = $props();
</script>

<Dialog.Root {open} {onOpenChange}>
  <Dialog.Content class="sm:max-w-lg">
    <Dialog.Header>
      <Dialog.Title class="break-words">Switch to “{corpusName}”?</Dialog.Title>
      <Dialog.Description>
        Switching corpus will <strong>clear the previous run’s in-view results</strong> (report,
        answer details, and activity). Knowledge-track results are not saved to disk — you would
        need to re-run the eval on the new corpus.
      </Dialog.Description>
    </Dialog.Header>

    <Dialog.Footer>
      <Button variant="outline" onclick={() => onOpenChange(false)}>Cancel</Button>
      <Button onclick={() => onConfirm()}>Switch corpus</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
