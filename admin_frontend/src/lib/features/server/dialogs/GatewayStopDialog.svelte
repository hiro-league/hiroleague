<script lang="ts">
  import ConfirmDialog from '$lib/components/ui/dialog/ConfirmDialog.svelte';
  import type { createGatewayStore } from '../state/gateway-store.svelte';

  let { gateway }: { gateway: ReturnType<typeof createGatewayStore> } = $props();
</script>

<ConfirmDialog
  open={gateway.dialog === 'stop'}
  onOpenChange={(next) => {
    if (!next) gateway.closeDialog();
  }}
  title="Stop gateway '{gateway.selected?.name ?? ''}'"
  message="This will stop the running gateway process."
  confirmLabel="Stop"
  pending={gateway.busy}
  onConfirm={gateway.submitStop}
/>
