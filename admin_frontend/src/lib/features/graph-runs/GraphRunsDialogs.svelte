<script lang="ts">
  import Button from '$lib/components/ui/button.svelte';
  import Modal from '$lib/ui/Modal.svelte';
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

<Modal open={memoryJsonRow !== null} title="Memory JSON" onClose={onCloseMemoryJson}>
  {#if memoryJsonRow}
    <pre class="memories-dialog-json">{JSON.stringify(memoryJsonRow, null, 2)}</pre>
  {/if}
  {#snippet footer()}
    <Button variant="outline" onclick={onCloseMemoryJson}>Close</Button>
  {/snippet}
</Modal>

<Modal open={clearMemoriesConfirmOpen} title="Clear all memories?" onClose={onCloseClearMemories}>
  <p class="font-sans text-sm text-muted-foreground">
    This deletes every long-term memory for the default user in this workspace.
  </p>
  {#snippet footer()}
    <Button variant="outline" disabled={memoryActionBusy} onclick={onCloseClearMemories}>Cancel</Button>
    <Button variant="destructive" disabled={memoryActionBusy} onclick={onConfirmClearMemories}>
      Clear all
    </Button>
  {/snippet}
</Modal>

<Modal
  open={deleteMemoryTarget !== null}
  title="Delete memory?"
  subtitle={deleteMemoryTarget ? memoryId(deleteMemoryTarget) : ''}
  onClose={onCloseDeleteMemory}
>
  {#if deleteMemoryTarget}
    <p class="font-sans text-sm text-muted-foreground">{memoryPrimaryText(deleteMemoryTarget)}</p>
  {/if}
  {#snippet footer()}
    <Button variant="outline" disabled={memoryActionBusy} onclick={onCloseDeleteMemory}>Cancel</Button>
    <Button variant="destructive" disabled={memoryActionBusy} onclick={onConfirmDeleteMemory}>
      Delete
    </Button>
  {/snippet}
</Modal>

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
