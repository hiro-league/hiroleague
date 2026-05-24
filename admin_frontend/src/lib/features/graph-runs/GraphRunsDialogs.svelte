<script lang="ts">
  import Button from '$lib/components/ui/button.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import { memoryId, memoryPrimaryText } from './graph-runs-pure';

  let {
    memoryJsonRow,
    clearMemoriesConfirmOpen,
    deleteMemoryTarget,
    memoryActionBusy,
    onCloseMemoryJson,
    onCloseClearMemories,
    onConfirmClearMemories,
    onCloseDeleteMemory,
    onConfirmDeleteMemory
  }: {
    memoryJsonRow: Record<string, unknown> | null;
    clearMemoriesConfirmOpen: boolean;
    deleteMemoryTarget: Record<string, unknown> | null;
    memoryActionBusy: boolean;
    onCloseMemoryJson: () => void;
    onCloseClearMemories: () => void;
    onConfirmClearMemories: () => void;
    onCloseDeleteMemory: () => void;
    onConfirmDeleteMemory: () => void;
  } = $props();
</script>

<Dialog.Root open={memoryJsonRow !== null} onOpenChange={(next) => { if (!next) onCloseMemoryJson(); }}>
  <Dialog.Content class="sm:max-w-2xl">
    <Dialog.Header>
      <Dialog.Title>Memory JSON</Dialog.Title>
    </Dialog.Header>
    {#if memoryJsonRow}
      <pre class="memories-dialog-json">{JSON.stringify(memoryJsonRow, null, 2)}</pre>
    {/if}
    <Dialog.Footer>
      <Button variant="outline" onclick={onCloseMemoryJson}>Close</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root open={clearMemoriesConfirmOpen} onOpenChange={(next) => { if (!next) onCloseClearMemories(); }}>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>Clear all memories?</Dialog.Title>
    </Dialog.Header>
    <p class="font-sans text-sm text-muted-foreground">
      This deletes every long-term memory for the default user in this workspace.
    </p>
    <Dialog.Footer>
      <Button variant="outline" disabled={memoryActionBusy} onclick={onCloseClearMemories}>Cancel</Button>
      <Button variant="destructive" disabled={memoryActionBusy} onclick={onConfirmClearMemories}>
        Clear all
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root open={deleteMemoryTarget !== null} onOpenChange={(next) => { if (!next) onCloseDeleteMemory(); }}>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>Delete memory?</Dialog.Title>
      {#if deleteMemoryTarget}
        <Dialog.Description>{memoryId(deleteMemoryTarget)}</Dialog.Description>
      {/if}
    </Dialog.Header>
    {#if deleteMemoryTarget}
      <p class="font-sans text-sm text-muted-foreground">{memoryPrimaryText(deleteMemoryTarget)}</p>
    {/if}
    <Dialog.Footer>
      <Button variant="outline" disabled={memoryActionBusy} onclick={onCloseDeleteMemory}>Cancel</Button>
      <Button variant="destructive" disabled={memoryActionBusy} onclick={onConfirmDeleteMemory}>
        Delete
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<style>
  .memories-dialog-json {
    margin: 0;
    padding: 10px;
    max-height: min(62vh, 620px);
    overflow: auto;
    font-size: 11px;
    line-height: 1.35;
    border-radius: 6px;
    background: color-mix(in srgb, var(--muted-foreground, #64748b) 8%, transparent);
    white-space: pre;
  }
</style>
