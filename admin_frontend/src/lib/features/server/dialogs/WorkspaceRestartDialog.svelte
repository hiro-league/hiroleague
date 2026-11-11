<script lang="ts">
  import { Checkbox } from '$kit/components/ui/checkbox/index.js';
  import { Button } from '$kit/components/ui/button/index.js';
  import * as Dialog from '$kit/components/ui/dialog/index.js';
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
      <Checkbox
        bind:checked={workspace.restartForm.admin}
        disabled={workspace.selected?.id === workspace.hostingWorkspaceId}
      />
      Also start Admin UI on the restarted process
    </label>
    {#if workspace.selected?.id === workspace.hostingWorkspaceId}
      <p class="rounded-md border border-warning/30 bg-warning/10 p-3 text-sm text-warning">
        This workspace is running the current Admin UI. Keep admin restart enabled.
      </p>
    {/if}
    <Dialog.Footer>
      <Button variant="outline" onclick={workspace.closeDialog}>Cancel</Button>
      <Button disabled={workspace.busy} onclick={workspace.submitRestart}>Restart</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
