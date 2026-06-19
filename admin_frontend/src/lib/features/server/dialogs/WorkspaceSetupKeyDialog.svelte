<script lang="ts">
  import Button from '$lib/components/ui/button.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import PublicKeyCopyField from '../shared/PublicKeyCopyField.svelte';
  import type { createWorkspaceStore } from '../state/workspace-store.svelte';

  let { workspace }: { workspace: ReturnType<typeof createWorkspaceStore> } = $props();
</script>

<Dialog.Root
  open={workspace.dialog === 'setup-key'}
  onOpenChange={(next) => { if (!next) workspace.closeDialog(); }}
>
  <Dialog.Content class="sm:max-w-xl">
    <Dialog.Header>
      <Dialog.Title>Workspace '{workspace.selected?.name ?? ''}' configured</Dialog.Title>
      <Dialog.Description>Save this public key before closing.</Dialog.Description>
    </Dialog.Header>
    <p class="rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-700 dark:text-amber-300">
      Save this key. It will not be shown again after setup. Paste it into the Desktop public key field when creating a gateway instance for this workspace.
    </p>
    <PublicKeyCopyField
      value={workspace.setupPublicKey}
      copied={workspace.copiedText === workspace.setupPublicKey}
      oncopy={() => workspace.copyText(workspace.setupPublicKey)}
    />
    <Dialog.Footer>
      <Button onclick={workspace.closeDialog}>I've saved the key</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
