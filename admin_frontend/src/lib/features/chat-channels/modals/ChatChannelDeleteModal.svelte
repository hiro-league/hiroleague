<script lang="ts">
  import type { ChatChannelRow } from '$lib/api/chat-channels';
  import Button from '$lib/components/ui/button.svelte';
  import Modal from '$lib/ui/Modal.svelte';

  type Props = {
    target: ChatChannelRow | null;
    busy: boolean;
    onClose: () => void;
    onConfirm: () => void;
  };

  let { target, busy, onClose, onConfirm }: Props = $props();
</script>

<Modal open={target !== null} title={`Delete channel '${target ? target.name : ''}'?`} {onClose}>
  <p class="font-sans text-sm text-muted-foreground">All messages in this channel will be removed.</p>
  {#snippet footer()}
    <Button variant="outline" onclick={onClose}>Cancel</Button>
    <Button variant="destructive" disabled={busy} onclick={onConfirm}>Delete</Button>
  {/snippet}
</Modal>
