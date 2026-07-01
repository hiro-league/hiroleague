<script lang="ts">
  /**
   * Inline "download this local model" affordance for embedder OR reranker picks. Only local-registry
   * ids appear in the status rows; cloud ids resolve to nothing (no download needed). `kind` selects
   * which controller state to read — one widget for both, shared by the model-picker download slot and
   * the embedder field.
   */
  import Button from '$lib/components/ui/button.svelte';
  import type { LocalEmbedderRow, LocalRerankerRow } from '$lib/api/knowledge';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';

  type Props = {
    ctrl: PreferencesController;
    /** Selects the embedder- vs reranker-specific controller state (lists, busy flags, callbacks). */
    kind: 'embedder' | 'reranker';
    /** The model id to show download status for (cloud ids are ignored). */
    modelId: string | null | undefined;
  };

  let { ctrl, kind, modelId }: Props = $props();

  const rows = $derived<(LocalEmbedderRow | LocalRerankerRow)[]>(
    kind === 'embedder' ? ctrl.localEmbedders : ctrl.localRerankers
  );
  const downloadingId = $derived(
    kind === 'embedder' ? ctrl.embedderDownloading : ctrl.rerankerDownloading
  );
  const kindBusy = $derived(kind === 'embedder' ? ctrl.embedderBusy : ctrl.rerankerBusy);

  const sel = $derived(modelId ? rows.find((m) => m.id === modelId) : undefined);
  const needsDownload = $derived(!!sel && !(sel.downloaded || sel.status === 'ready'));
  const downloading = $derived(!!sel && (sel.status === 'downloading' || downloadingId === sel.id));

  function start(id: string) {
    if (kind === 'embedder') void ctrl.downloadEmbedder(id);
    else void ctrl.downloadReranker(id);
  }
  function cancel(id: string) {
    if (kind === 'embedder') void ctrl.cancelEmbedder(id);
    else void ctrl.cancelReranker(id);
  }
</script>

{#if sel && needsDownload}
  <div class="grid gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2">
    <div class="flex items-center justify-between gap-3">
      <div class="min-w-0 font-sans text-xs">
        <span class="font-medium">
          {downloading ? 'Downloading…' : "This local model isn't downloaded yet"}
        </span>
        <span class="text-muted-foreground">
          · {sel.size_label}{#if downloading && sel.percent != null} · {sel.percent}%{/if}
        </span>
        {#if sel.status === 'error' && sel.error}
          <div class="text-destructive">{sel.error}</div>
        {/if}
      </div>
      <div class="shrink-0">
        {#if downloading}
          <Button variant="outline" size="sm" onclick={() => cancel(sel.id)}>Cancel</Button>
        {:else}
          <Button
            variant="outline"
            size="sm"
            disabled={ctrl.busy || kindBusy}
            onclick={() => start(sel.id)}
          >
            {sel.status === 'error' ? 'Retry download' : 'Download'}
          </Button>
        {/if}
      </div>
    </div>
    {#if downloading}
      <div class="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div
          class="h-full rounded-full bg-amber-500 transition-[width] duration-500"
          style="width: {sel.percent ?? 3}%"
        ></div>
      </div>
    {/if}
  </div>
{/if}
