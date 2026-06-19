<script lang="ts">
  import Button from '$lib/components/ui/button.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import type { createGatewayStore } from '../state/gateway-store.svelte';

  let { gateway }: { gateway: ReturnType<typeof createGatewayStore> } = $props();
</script>

<Dialog.Root
  open={gateway.dialog === 'remove'}
  onOpenChange={(next) => { if (!next) gateway.closeDialog(); }}
>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>Remove gateway '{gateway.selected?.name ?? ''}'</Dialog.Title>
      {#if gateway.selected?.path}
        <Dialog.Description>{gateway.selected.path}</Dialog.Description>
      {/if}
    </Dialog.Header>
    <label class="flex items-center gap-2 font-sans text-sm">
      <input type="checkbox" bind:checked={gateway.removeForm.purge} />
      Also delete instance files from disk
    </label>
    <Dialog.Footer>
      <Button variant="outline" onclick={gateway.closeDialog}>Cancel</Button>
      <Button variant="destructive" disabled={gateway.busy} onclick={gateway.submitRemove}>Remove</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
