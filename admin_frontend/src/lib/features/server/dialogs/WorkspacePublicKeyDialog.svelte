<script lang="ts">
  import { Button } from '$kit/components/ui/button/index.js';
  import * as Dialog from '$kit/components/ui/dialog/index.js';
  import PublicKeyCopyField from '../shared/PublicKeyCopyField.svelte';
  import type { createWorkspaceStore } from '../state/workspace-store.svelte';

  let { workspace }: { workspace: ReturnType<typeof createWorkspaceStore> } = $props();
</script>

<Dialog.Root
  open={workspace.dialog === 'public-key'}
  onOpenChange={(next) => { if (!next) workspace.closeDialog(); }}
>
  <Dialog.Content class="sm:max-w-xl">
    <Dialog.Header>
      <Dialog.Title>Public key - '{workspace.selected?.name ?? ''}'</Dialog.Title>
      <Dialog.Description>Regenerating invalidates existing gateway trust.</Dialog.Description>
    </Dialog.Header>
    <p class="rounded-md border border-warning/30 bg-warning/10 p-3 text-sm text-warning">
      This key must be registered in every gateway instance that trusts this workspace. Regenerating it invalidates all existing gateway trust relationships.
    </p>
    <PublicKeyCopyField
      value={workspace.publicKey}
      copied={workspace.copiedText === workspace.publicKey}
      oncopy={() => workspace.copyText(workspace.publicKey)}
    />
    <Dialog.Footer>
      <Button variant="destructive" disabled={workspace.busy} onclick={workspace.regenerateKey}>Regenerate key</Button>
      <Button variant="outline" onclick={workspace.closeDialog}>Close</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
