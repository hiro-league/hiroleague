<script lang="ts">
  import Button from '$lib/components/ui/button.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import InlineLoading from '$lib/ui/InlineLoading.svelte';
  import type { GraphChunkDetail } from '$lib/api/knowledge';
  import { memoryDateDisplay, memoryPrimaryText } from './shared/memory-pure';

  let {
    memoryJsonRow,
    memoryProvenanceRow,
    memoryProvenanceChunks,
    memoryProvenanceLoading,
    memoryProvenanceError,
    clearMemoriesConfirmOpen,
    clearGroupConfirmOpen,
    clearableMemoryCount,
    selectedGroupLabel,
    memoryActionBusy,
    onCloseMemoryJson,
    onCloseProvenance,
    onCloseClearMemories,
    onConfirmClearMemories,
    onCloseClearGroup,
    onConfirmClearGroup
  }: {
    memoryJsonRow: Record<string, unknown> | null;
    memoryProvenanceRow: Record<string, unknown> | null;
    memoryProvenanceChunks: GraphChunkDetail[];
    memoryProvenanceLoading: boolean;
    memoryProvenanceError: string;
    clearMemoriesConfirmOpen: boolean;
    clearGroupConfirmOpen: boolean;
    clearableMemoryCount: number;
    selectedGroupLabel: string;
    memoryActionBusy: boolean;
    onCloseMemoryJson: () => void;
    onCloseProvenance: () => void;
    onCloseClearMemories: () => void;
    onConfirmClearMemories: () => void;
    onCloseClearGroup: () => void;
    onConfirmClearGroup: () => void;
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

<Dialog.Root open={memoryProvenanceRow !== null} onOpenChange={(next) => { if (!next) onCloseProvenance(); }}>
  <Dialog.Content class="sm:max-w-2xl">
    <Dialog.Header>
      <Dialog.Title>Source turns</Dialog.Title>
      <Dialog.Description>The conversation turn(s) this fact was extracted from.</Dialog.Description>
    </Dialog.Header>
    {#if memoryProvenanceRow}
      <p class="memories-provenance-fact">{memoryPrimaryText(memoryProvenanceRow)}</p>
    {/if}
    {#if memoryProvenanceLoading}
      <InlineLoading label="Loading source turns…" class="m-0" />
    {:else if memoryProvenanceError}
      <p class="font-sans text-sm text-destructive" role="alert">{memoryProvenanceError}</p>
    {:else if memoryProvenanceChunks.length === 0}
      <p class="font-sans text-sm text-muted-foreground">
        No source turn available — this is an entity summary (accumulated across turns) or the
        originating episode is no longer present.
      </p>
    {:else}
      <ul class="memories-provenance-list">
        {#each memoryProvenanceChunks as chunk (chunk.id)}
          {@const when = memoryDateDisplay(chunk.valid_at)}
          <li class="memories-provenance-item">
            <div class="memories-provenance-meta">
              <span>{chunk.document_title || 'Conversation'}</span>
              {#if when.date !== '—'}<span title={when.title}>{when.date} {when.time}</span>{/if}
            </div>
            <p class="memories-provenance-text">{chunk.text}</p>
          </li>
        {/each}
      </ul>
    {/if}
    <Dialog.Footer>
      <Button variant="outline" onclick={onCloseProvenance}>Close</Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root open={clearMemoriesConfirmOpen} onOpenChange={(next) => { if (!next) onCloseClearMemories(); }}>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>
        Delete {clearableMemoryCount} {clearableMemoryCount === 1 ? 'memory' : 'memories'}?
      </Dialog.Title>
    </Dialog.Header>
    <p class="font-sans text-sm text-muted-foreground">
      This permanently deletes the filtered facts currently shown. Entities and episodes are
      kept (use “Clear group” to wipe those). This can't be undone.
    </p>
    <Dialog.Footer>
      <Button variant="outline" disabled={memoryActionBusy} onclick={onCloseClearMemories}>Cancel</Button>
      <Button variant="destructive" disabled={memoryActionBusy} onclick={onConfirmClearMemories}>
        Delete
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root open={clearGroupConfirmOpen} onOpenChange={(next) => { if (!next) onCloseClearGroup(); }}>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>Clear the entire “{selectedGroupLabel}” group?</Dialog.Title>
    </Dialog.Header>
    <p class="font-sans text-sm text-muted-foreground">
      This permanently wipes the whole partition — <strong>all facts, entities, episodes, and
      communities</strong> in this group, not just what's shown. The group itself will disappear
      from the selector. This can't be undone.
    </p>
    <Dialog.Footer>
      <Button variant="outline" disabled={memoryActionBusy} onclick={onCloseClearGroup}>Cancel</Button>
      <Button variant="destructive" disabled={memoryActionBusy} onclick={onConfirmClearGroup}>
        Clear group
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

  .memories-provenance-fact {
    margin: 0;
    font-family: var(--font-sans);
    font-size: 13px;
    font-weight: 600;
  }

  .memories-provenance-list {
    margin: 0;
    padding: 0;
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 10px;
    max-height: min(56vh, 560px);
    overflow: auto;
  }

  .memories-provenance-item {
    border-radius: 6px;
    padding: 10px;
    background: color-mix(in srgb, var(--muted-foreground, #64748b) 8%, transparent);
  }

  .memories-provenance-meta {
    display: flex;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 6px;
    font-family: var(--font-sans);
    font-size: 11px;
    color: var(--muted-foreground, #64748b);
  }

  .memories-provenance-text {
    margin: 0;
    font-family: var(--font-sans);
    font-size: 13px;
    line-height: 1.45;
    white-space: pre-wrap;
    word-break: break-word;
  }
</style>
