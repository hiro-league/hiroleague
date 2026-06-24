<script lang="ts">
  import ConfirmDialog from '$lib/components/ui/dialog/ConfirmDialog.svelte';

  type Props = {
    open: boolean;
    channelName: string;
    busy: boolean;
    onClose: () => void;
    onConfirm: () => void;
  };

  let { open, channelName, busy, onClose, onConfirm }: Props = $props();
</script>

<ConfirmDialog
  {open}
  onOpenChange={(next) => {
    if (!next) onClose();
  }}
  title="Clear all messages in this channel?"
  confirmLabel="Clear messages"
  pending={busy}
  disableCancelWhenPending={true}
  {onConfirm}
>
  {#snippet children()}
    <p class="font-sans text-sm text-muted-foreground">
      This removes every message and attachment in
      <strong class="text-foreground">{channelName}</strong>
      on the server. The channel itself stays. Hiro devices pick this up on the next
      <span class="font-mono text-xs">channels.list</span> sync.
    </p>
  {/snippet}
</ConfirmDialog>
