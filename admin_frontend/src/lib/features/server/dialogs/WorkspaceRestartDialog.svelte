<script lang="ts">
  import Button from '$lib/components/ui/button.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import type { createWorkspaceStore } from '../state/workspace-store.svelte';

  let { workspace }: { workspace: ReturnType<typeof createWorkspaceStore> } = $props();
</script>

<Dialog.Root
  open={workspace.dialog === 'restart'}
  onOpenChange={(next) => { if (!next) workspace.closeDialog(); }}
>
  <Dialog.Content class="sm:max-w-xl">
    <Dialog.Header>
      <Dialog.Title>Restart workspace '{workspace.selected?.name ?? ''}'</Dialog.Title>
      {#if workspace.selected?.path}
        <Dialog.Description>{workspace.selected.path}</Dialog.Description>
      {/if}
    </Dialog.Header>
    <label class="flex items-center gap-2 font-sans text-sm">
      <input
        type="checkbox"
        bind:checked={workspace.restartForm.admin}
        disabled={workspace.selected?.id === workspace.hostingWorkspaceId}
      />
      Also start Admin UI on the restarted process
    </label>
    {#if workspace.selected?.id === workspace.hostingWorkspaceId}
      <p class="rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-700 dark:text-amber-300">
        This workspace is running the current Admin UI. Keep admin restart enabled.
      </p>
    {/if}
    <Dialog.Footer>
      <Button variant="outline" onclick={workspace.closeDialog}>Cancel</Button>
      <Button disabled={workspace.busy} onclick={workspace.submitRestart}>Restart</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
