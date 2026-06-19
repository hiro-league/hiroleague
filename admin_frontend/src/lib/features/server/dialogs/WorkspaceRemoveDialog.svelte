<script lang="ts">
  import Button from '$lib/components/ui/button.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import type { createWorkspaceStore } from '../state/workspace-store.svelte';

  let { workspace }: { workspace: ReturnType<typeof createWorkspaceStore> } = $props();
</script>

<Dialog.Root
  open={workspace.dialog === 'remove'}
  onOpenChange={(next) => { if (!next) workspace.closeDialog(); }}
>
  <Dialog.Content class="sm:max-w-xl">
    <Dialog.Header>
      <Dialog.Title>Remove workspace '{workspace.selected?.name ?? ''}'</Dialog.Title>
      {#if workspace.selected?.path}
        <Dialog.Description>{workspace.selected.path}</Dialog.Description>
      {/if}
    </Dialog.Header>
    <label class="flex items-center gap-2 font-sans text-sm">
      <input type="checkbox" bind:checked={workspace.removeForm.purge} />
      Also delete workspace folder from disk
    </label>
    <Dialog.Footer>
      <Button variant="outline" onclick={workspace.closeDialog}>Cancel</Button>
      <Button variant="destructive" disabled={workspace.busy} onclick={workspace.submitRemove}>Remove</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
