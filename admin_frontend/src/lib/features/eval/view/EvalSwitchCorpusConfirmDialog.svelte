<!--
  Confirm dialog when switching corpus on the KNOWLEDGE track while a completed/failed run's
  in-view results would be discarded (memory track persists per corpus, so no prompt there).
-->
<script lang="ts">
  import ConfirmDialog from '$lib/components/ui/dialog/ConfirmDialog.svelte';
  import * as Dialog from '$lib/components/ui/dialog';

  type Props = {
    open: boolean;
    corpusName: string;
    onOpenChange: (open: boolean) => void;
    onConfirm: () => void;
  };

  let { open, corpusName, onOpenChange, onConfirm }: Props = $props();
</script>

<ConfirmDialog
  {open}
  {onOpenChange}
  title={`Switch to “${corpusName}”?`}
  confirmLabel="Switch corpus"
  destructive={false}
  widthClass="sm:max-w-lg"
  {onConfirm}
>
  {#snippet description()}
    <Dialog.Description>
      Switching corpus will <strong>clear the previous run’s in-view results</strong> (report,
      answer details, and activity). Knowledge-track results are not saved to disk — you would
      need to re-run the eval on the new corpus.
    </Dialog.Description>
  {/snippet}
</ConfirmDialog>
