<script lang="ts">
  import Button from '$lib/components/ui/button.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import type { createGatewayStore } from '../state/gateway-store.svelte';

  let { gateway }: { gateway: ReturnType<typeof createGatewayStore> } = $props();
</script>

<Dialog.Root
  open={gateway.dialog === 'stop'}
  onOpenChange={(next) => { if (!next) gateway.closeDialog(); }}
>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>Stop gateway '{gateway.selected?.name ?? ''}'</Dialog.Title>
    </Dialog.Header>
    <p class="text-sm text-muted-foreground">This will stop the running gateway process.</p>
    <Dialog.Footer>
      <Button variant="outline" onclick={gateway.closeDialog}>Cancel</Button>
      <Button variant="destructive" disabled={gateway.busy} onclick={gateway.submitStop}>Stop</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
