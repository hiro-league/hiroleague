<script lang="ts">
  import * as Dialog from '$lib/components/ui/dialog';
  import Button from '$lib/components/ui/button.svelte';
  import CharacterPhotoCropModal from '$lib/features/characters/modals/CharacterPhotoCropModal.svelte';
  import type { createCharactersPageController } from '$lib/features/characters/state/characters-controller.svelte';
  import type { createUnsavedGuard } from '$lib/navigation/unsaved-guard.svelte';

  let {
    ctrl,
    unsaved,
    characterId
  }: {
    ctrl: ReturnType<typeof createCharactersPageController>;
    unsaved: ReturnType<typeof createUnsavedGuard>;
    characterId: string | null;
  } = $props();
</script>

<Dialog.Root
  open={ctrl.deleteOpen}
  onOpenChange={(next) => {
    if (!next && !ctrl.busy) ctrl.deleteOpen = false;
  }}
>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>Delete '{characterId}'?</Dialog.Title>
      <Dialog.Description>This removes the character folder and index row.</Dialog.Description>
    </Dialog.Header>
    <p class="text-sm text-muted-foreground">This action cannot be undone.</p>
    <Dialog.Footer>
      <Button variant="outline" disabled={ctrl.busy} onclick={() => (ctrl.deleteOpen = false)}
        >Cancel</Button
      >
      <Button variant="destructive" disabled={ctrl.busy} onclick={() => void ctrl.confirmDelete()}
        >Delete</Button
      >
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<CharacterPhotoCropModal
  open={ctrl.photoCrop.cropOpen}
  busy={ctrl.busy}
  cropZoom={ctrl.photoCrop.cropZoom}
  cropX={ctrl.photoCrop.cropX}
  cropY={ctrl.photoCrop.cropY}
  onDismiss={() => ctrl.photoCrop.dismissCropModal()}
  onCropZoomChange={ctrl.photoCrop.handleCropZoom}
  onCropXChange={ctrl.photoCrop.handleCropPanX}
  onCropYChange={ctrl.photoCrop.handleCropPanY}
  onCropCanvasChange={ctrl.photoCrop.handleCropCanvas}
  onSubmitPhoto={() => void ctrl.photoCrop.submitPhoto()}
/>

<Dialog.Root
  open={unsaved.unsavedModalOpen}
  onOpenChange={(next) => {
    if (!next) unsaved.closeUnsavedModalContinueEditing();
  }}
>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>Unsaved changes</Dialog.Title>
      <Dialog.Description>You have edits that are not saved yet.</Dialog.Description>
    </Dialog.Header>
    <p class="text-sm text-muted-foreground">
      Discard them and leave, or stay on this page to keep editing.
    </p>
    <Dialog.Footer>
      <Button variant="outline" onclick={unsaved.closeUnsavedModalContinueEditing}
        >Continue editing</Button
      >
      <Button variant="destructive" onclick={unsaved.confirmUnsavedModalDiscard}
        >Discard changes</Button
      >
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
