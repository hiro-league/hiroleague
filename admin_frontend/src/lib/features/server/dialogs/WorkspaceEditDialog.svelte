<script lang="ts">
  import { Checkbox } from '$kit/components/ui/checkbox/index.js';
  import { Button } from '$kit/components/ui/button/index.js';
  import Field from '$kit/ui/field.svelte';
  import * as Dialog from '$kit/components/ui/dialog/index.js';
  import { Input } from '$kit/components/ui/input/index.js';
  import type { createWorkspaceStore } from '../state/workspace-store.svelte';

  let { workspace }: { workspace: ReturnType<typeof createWorkspaceStore> } = $props();
  const uid = $props.id();
</script>

<Dialog.Root
  open={workspace.dialog === 'edit'}
  onOpenChange={(next) => { if (!next) workspace.closeDialog(); }}
>
  <Dialog.Content class="sm:max-w-xl">
    <Dialog.Header>
      <Dialog.Title>Edit workspace '{workspace.selected?.name ?? ''}'</Dialog.Title>
    </Dialog.Header>
    <div class="grid gap-4">
      <Field label="Display name" for="{uid}-name">
        <Input id="{uid}-name" bind:value={workspace.editForm.name} />
      </Field>
      <Field label="Gateway WebSocket URL" for="{uid}-gateway">
        <Input id="{uid}-gateway" bind:value={workspace.editForm.gatewayUrl} placeholder="ws://myhost:8765" />
      </Field>
      <label class="flex items-center gap-2 font-sans text-sm">
        <Checkbox bind:checked={workspace.editForm.setDefault} />
        Set as default workspace
      </label>
    </div>
    <Dialog.Footer>
      <Button variant="outline" onclick={workspace.closeDialog}>Cancel</Button>
      <Button disabled={workspace.busy} onclick={workspace.submitEdit}>Save</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
