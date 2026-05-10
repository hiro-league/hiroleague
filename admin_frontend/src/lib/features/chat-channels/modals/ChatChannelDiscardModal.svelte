<script lang="ts">
  import Button from '$lib/components/ui/button.svelte';
  import Modal from '$lib/ui/Modal.svelte';

  type Props = {
    open: boolean;
    onKeepEditing: () => void;
    onDiscard: () => void;
  };

  let { open, onKeepEditing, onDiscard }: Props = $props();
</script>

<Modal open={open} title="Discard changes?" overlayClass="z-[60]" onClose={onKeepEditing}>
  <p class="font-sans text-sm text-muted-foreground">
    You have unsaved edits for this conversation channel. Discard them or keep editing.
  </p>
  {#snippet footer()}
    <Button variant="outline" onclick={onKeepEditing}>Keep editing</Button>
    <Button variant="destructive" onclick={onDiscard}>Discard</Button>
  {/snippet}
</Modal>
