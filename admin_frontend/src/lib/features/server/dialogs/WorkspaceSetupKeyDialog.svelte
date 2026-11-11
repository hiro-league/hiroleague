<script lang="ts">
  import { Button } from '$kit/components/ui/button/index.js';
  import * as Dialog from '$kit/components/ui/dialog/index.js';
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
    <p class="rounded-md border border-warning/30 bg-warning/10 p-3 text-sm text-warning">
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
