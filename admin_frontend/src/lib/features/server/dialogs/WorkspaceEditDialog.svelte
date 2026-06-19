<script lang="ts">
  import Button from '$lib/components/ui/button.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import type { createWorkspaceStore } from '../state/workspace-store.svelte';

  let { workspace }: { workspace: ReturnType<typeof createWorkspaceStore> } = $props();
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
      <FormField label="Display name">
        {#snippet children()}
          <input bind:value={workspace.editForm.name} />
        {/snippet}
      </FormField>
      <FormField label="Gateway WebSocket URL">
        {#snippet children()}
          <input bind:value={workspace.editForm.gatewayUrl} placeholder="ws://myhost:8765" />
        {/snippet}
      </FormField>
      <label class="flex items-center gap-2 font-sans text-sm">
        <input type="checkbox" bind:checked={workspace.editForm.setDefault} />
        Set as default workspace
      </label>
    </div>
    <Dialog.Footer>
      <Button variant="outline" onclick={workspace.closeDialog}>Cancel</Button>
      <Button disabled={workspace.busy} onclick={workspace.submitEdit}>Save</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
