<script lang="ts">
  import { Checkbox } from '$kit/components/ui/checkbox/index.js';
  import { Button } from '$kit/components/ui/button/index.js';
  import Field from '$kit/ui/field.svelte';
  import * as Dialog from '$kit/components/ui/dialog/index.js';
  import { Input } from '$kit/components/ui/input/index.js';
  import { Textarea } from '$kit/components/ui/textarea/index.js';
  import type { createGatewayStore } from '../state/gateway-store.svelte';

  let { gateway }: { gateway: ReturnType<typeof createGatewayStore> } = $props();
  const uid = $props.id();
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
      <Field label="Name" for="{uid}-name">
        <Input id="{uid}-name" bind:value={gateway.createForm.name} placeholder="e.g. main" />
      </Field>
      <Field label="Desktop public key" for="{uid}-key">
        <Textarea id="{uid}-key" bind:value={gateway.createForm.desktopPublicKey} placeholder="Paste the workspace public key here" />
      </Field>
      <Field label="Port" for="{uid}-port">
        <Input id="{uid}-port" bind:value={gateway.createForm.port} inputmode="numeric" placeholder="8765" />
      </Field>
      <details class="grid gap-3 rounded-md border bg-muted/40 p-3">
        <summary class="cursor-pointer font-sans font-semibold">Advanced options</summary>
        <Field label="Host" for="{uid}-host">
          <Input id="{uid}-host" bind:value={gateway.createForm.host} placeholder="0.0.0.0" />
        </Field>
        <label class="flex items-center gap-2 font-sans text-sm">
          <Checkbox bind:checked={gateway.createForm.makeDefault} />
          Set as default gateway instance
        </label>
        <label class="flex items-center gap-2 font-sans text-sm">
          <Checkbox bind:checked={gateway.createForm.skipAutostart} />
          Skip auto-start registration
        </label>
        <label class="flex items-center gap-2 font-sans text-sm">
          <Checkbox bind:checked={gateway.createForm.elevatedTask} />
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
