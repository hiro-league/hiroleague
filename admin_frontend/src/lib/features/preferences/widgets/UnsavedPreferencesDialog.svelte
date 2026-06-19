<script lang="ts">
  import Button from '$lib/components/ui/button.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import type { createUnsavedGuard } from '$lib/navigation/unsaved-guard.svelte';

  type Props = {
    unsaved: ReturnType<typeof createUnsavedGuard>;
    onDiscard: () => void;
  };

  let { unsaved, onDiscard }: Props = $props();
</script>

<Dialog.Root
  open={unsaved.unsavedModalOpen}
  onOpenChange={(next) => {
    if (!next) unsaved.closeUnsavedModalContinueEditing();
  }}
>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>Discard unsaved preferences?</Dialog.Title>
    </Dialog.Header>
    <p class="text-sm text-muted-foreground">
      You have unsaved workspace preference changes. Discard them and leave, or keep editing.
    </p>
    <Dialog.Footer>
      <Button variant="outline" onclick={unsaved.closeUnsavedModalContinueEditing}>
        Keep editing
      </Button>
      <Button variant="destructive" onclick={onDiscard}>Discard changes</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
