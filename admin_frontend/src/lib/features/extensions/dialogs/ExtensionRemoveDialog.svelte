<script lang="ts">
  import ConfirmDialog from '$kit/ui/confirm-dialog.svelte';
  import type { ExtensionsController } from '../state/extensions-controller.svelte';

  let { ctrl }: { ctrl: ExtensionsController } = $props();
</script>

<ConfirmDialog
  open={ctrl.removeTarget !== null}
  onOpenChange={(next) => {
    if (!next) ctrl.closeRemove();
  }}
  title="Remove '{ctrl.removeTarget?.name || 'extension'}'?"
  message="It is disconnected now and refused until it is paired again with a new code."
  confirmLabel="Remove"
  pending={ctrl.busy}
  onConfirm={() => void ctrl.submitRemove()}
/>
