<script lang="ts">
  import Button from '$lib/components/ui/button.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import type { DevicesController } from '../state/devices-controller.svelte';

  type Props = {
    ctrl: DevicesController;
  };

  let { ctrl }: Props = $props();
</script>

<Dialog.Root
  open={ctrl.revokeTarget !== null}
  onOpenChange={(next) => {
    if (!next) ctrl.closeRevoke();
  }}
>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>Revoke '{ctrl.revokeDisplayName}'?</Dialog.Title>
    </Dialog.Header>
    <p class="text-sm text-muted-foreground">This device will no longer be able to connect.</p>
    <Dialog.Footer>
      <Button variant="outline" onclick={() => ctrl.closeRevoke()}>Cancel</Button>
      <Button variant="destructive" disabled={ctrl.busy} onclick={() => void ctrl.submitRevoke()}>
        Revoke
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
