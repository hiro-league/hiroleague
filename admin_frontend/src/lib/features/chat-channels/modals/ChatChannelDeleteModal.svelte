<script lang="ts">
  import type { ChatChannelRow } from '$lib/api/chat-channels';
  import ConfirmDialog from '$lib/components/ui/dialog/ConfirmDialog.svelte';

  type Props = {
    target: ChatChannelRow | null;
    busy: boolean;
    onClose: () => void;
    onConfirm: () => void;
  };

  let { target, busy, onClose, onConfirm }: Props = $props();
</script>

<ConfirmDialog
  open={target !== null}
  onOpenChange={(next) => {
    if (!next) onClose();
  }}
  title="Delete channel '{target ? target.name : ''}'?"
  message="All messages in this channel will be removed."
  confirmLabel="Delete"
  pending={busy}
  {onConfirm}
/>
