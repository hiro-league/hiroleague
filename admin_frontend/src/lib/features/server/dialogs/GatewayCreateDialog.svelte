<script lang="ts">
  import Button from '$lib/components/ui/button.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import type { createGatewayStore } from '../state/gateway-store.svelte';

  let { gateway }: { gateway: ReturnType<typeof createGatewayStore> } = $props();
</script>

<Dialog.Root
  open={gateway.dialog === 'create'}
  onOpenChange={(next) => { if (!next) gateway.closeDialog(); }}
>
  <Dialog.Content class="max-h-[calc(100vh-2rem)] overflow-y-auto sm:max-w-xl">
    <Dialog.Header>
      <Dialog.Title>Create gateway instance</Dialog.Title>
    </Dialog.Header>
    <div class="grid gap-4">
      <FormField label="Name">
        {#snippet children()}
          <input bind:value={gateway.createForm.name} placeholder="e.g. main" />
        {/snippet}
      </FormField>
      <FormField label="Desktop public key">
        {#snippet children()}
          <textarea bind:value={gateway.createForm.desktopPublicKey} placeholder="Paste the workspace public key here"></textarea>
        {/snippet}
      </FormField>
      <FormField label="Port">
        {#snippet children()}
          <input bind:value={gateway.createForm.port} inputmode="numeric" placeholder="8765" />
        {/snippet}
      </FormField>
      <details class="grid gap-3 rounded-md border bg-muted/40 p-3">
        <summary class="cursor-pointer font-sans font-semibold">Advanced options</summary>
        <FormField label="Host">
          {#snippet children()}
            <input bind:value={gateway.createForm.host} placeholder="0.0.0.0" />
          {/snippet}
        </FormField>
        <label class="flex items-center gap-2 font-sans text-sm">
          <input type="checkbox" bind:checked={gateway.createForm.makeDefault} />
          Set as default gateway instance
        </label>
        <label class="flex items-center gap-2 font-sans text-sm">
          <input type="checkbox" bind:checked={gateway.createForm.skipAutostart} />
          Skip auto-start registration
        </label>
        <label class="flex items-center gap-2 font-sans text-sm">
          <input type="checkbox" bind:checked={gateway.createForm.elevatedTask} />
          Request elevated Task Scheduler entry
        </label>
      </details>
    </div>
    <Dialog.Footer>
      <Button variant="outline" onclick={gateway.closeDialog}>Cancel</Button>
      <Button disabled={gateway.busy} onclick={gateway.submitCreate}>Create</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
