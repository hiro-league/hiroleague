<script lang="ts">
  import ConfirmDialog from '$lib/components/ui/dialog/ConfirmDialog.svelte';
  import type { createWorkspaceStore } from '../state/workspace-store.svelte';

  let { workspace }: { workspace: ReturnType<typeof createWorkspaceStore> } = $props();
</script>

<ConfirmDialog
  open={workspace.dialog === 'remove'}
  onOpenChange={(next) => {
    if (!next) workspace.closeDialog();
  }}
  title="Remove workspace '{workspace.selected?.name ?? ''}'"
  message={workspace.selected?.path}
  confirmLabel="Remove"
  pending={workspace.busy}
  widthClass="sm:max-w-xl"
  onConfirm={workspace.submitRemove}
>
  {#snippet children()}
    <label class="flex items-center gap-2 font-sans text-sm">
      <input type="checkbox" bind:checked={workspace.removeForm.purge} />
      Also delete workspace folder from disk
    </label>
  {/snippet}
</ConfirmDialog>
