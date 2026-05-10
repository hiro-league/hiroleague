<script lang="ts">
  import Button from '$lib/components/ui/button.svelte';
  import Modal from '$lib/ui/Modal.svelte';

  type Props = {
    open: boolean;
    channelName: string;
    busy: boolean;
    onClose: () => void;
    onConfirm: () => void;
  };

  let { open, channelName, busy, onClose, onConfirm }: Props = $props();
</script>

<Modal {open} title="Clear all messages in this channel?" {onClose}>
  <p class="font-sans text-sm text-muted-foreground">
    This removes every message and attachment in
    <strong class="text-foreground">{channelName}</strong>
    on the server. The channel itself stays. Hiro devices pick this up on the next
    <span class="font-mono text-xs">channels.list</span> sync.
  </p>
  {#snippet footer()}
    <Button variant="outline" disabled={busy} onclick={onClose}>Cancel</Button>
    <Button variant="destructive" disabled={busy} onclick={onConfirm}>Clear messages</Button>
  {/snippet}
</Modal>
