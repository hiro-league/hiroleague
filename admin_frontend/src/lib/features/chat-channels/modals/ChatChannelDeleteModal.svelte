<script lang="ts">
  import type { ChatChannelRow } from '$lib/api/chat-channels';
  import Button from '$lib/components/ui/button.svelte';
  import * as Dialog from '$lib/components/ui/dialog';

  type Props = {
    target: ChatChannelRow | null;
    busy: boolean;
    onClose: () => void;
    onConfirm: () => void;
  };

  let { target, busy, onClose, onConfirm }: Props = $props();
</script>

<Dialog.Root open={target !== null} onOpenChange={(next) => { if (!next) onClose(); }}>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>Delete channel '{target ? target.name : ''}'?</Dialog.Title>
    </Dialog.Header>
    <p class="font-sans text-sm text-muted-foreground">All messages in this channel will be removed.</p>
    <Dialog.Footer>
      <Button variant="outline" onclick={onClose}>Cancel</Button>
      <Button variant="destructive" disabled={busy} onclick={onConfirm}>Delete</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
