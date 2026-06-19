<script lang="ts">
  import Button from '$lib/components/ui/button.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
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
    <p class="rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-700 dark:text-amber-300">
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
