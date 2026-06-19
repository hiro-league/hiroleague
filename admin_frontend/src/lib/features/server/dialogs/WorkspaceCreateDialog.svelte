<script lang="ts">
  import Button from '$lib/components/ui/button.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import type { createWorkspaceStore } from '../state/workspace-store.svelte';

  let { workspace }: { workspace: ReturnType<typeof createWorkspaceStore> } = $props();
</script>

<Dialog.Root
  open={workspace.dialog === 'create'}
  onOpenChange={(next) => { if (!next) workspace.closeDialog(); }}
>
  <Dialog.Content class="sm:max-w-xl">
    <Dialog.Header>
      <Dialog.Title>Create workspace</Dialog.Title>
    </Dialog.Header>
    <div class="grid gap-4">
      <FormField label="Name">
        {#snippet children()}
          <input bind:value={workspace.createForm.name} placeholder="e.g. work" />
        {/snippet}
      </FormField>
      <FormField label="Path (optional)">
        {#snippet children()}
          <input bind:value={workspace.createForm.path} placeholder="Leave blank for default location" />
        {/snippet}
      </FormField>
    </div>
    <Dialog.Footer>
      <Button variant="outline" onclick={workspace.closeDialog}>Cancel</Button>
      <Button disabled={workspace.busy} onclick={workspace.submitCreate}>Create</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
