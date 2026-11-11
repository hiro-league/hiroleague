<script lang="ts">
  import { Checkbox } from '$kit/components/ui/checkbox/index.js';
  import ConfirmDialog from '$lib/ui/ConfirmDialog.svelte';
  import type { createGatewayStore } from '../state/gateway-store.svelte';

  let { gateway }: { gateway: ReturnType<typeof createGatewayStore> } = $props();
</script>

<ConfirmDialog
  open={gateway.dialog === 'remove'}
  onOpenChange={(next) => {
    if (!next) gateway.closeDialog();
  }}
  title="Remove gateway '{gateway.selected?.name ?? ''}'"
  message={gateway.selected?.path}
  confirmLabel="Remove"
  pending={gateway.busy}
  onConfirm={gateway.submitRemove}
>
  {#snippet children()}
    <label class="flex items-center gap-2 font-sans text-sm">
      <Checkbox bind:checked={gateway.removeForm.purge} />
      Also delete instance files from disk
    </label>
  {/snippet}
</ConfirmDialog>
