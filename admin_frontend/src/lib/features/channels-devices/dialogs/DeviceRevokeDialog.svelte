<script lang="ts">
  import ConfirmDialog from '$lib/components/ui/dialog/ConfirmDialog.svelte';
  import type { DevicesController } from '../state/devices-controller.svelte';

  type Props = {
    ctrl: DevicesController;
  };

  let { ctrl }: Props = $props();
</script>

<ConfirmDialog
  open={ctrl.revokeTarget !== null}
  onOpenChange={(next) => {
    if (!next) ctrl.closeRevoke();
  }}
  title="Revoke '{ctrl.revokeDisplayName}'?"
  message="This device will no longer be able to connect."
  confirmLabel="Revoke"
  pending={ctrl.busy}
  onConfirm={() => void ctrl.submitRevoke()}
/>
