<script lang="ts">
  import Button from '$lib/components/ui/button.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';

  type Props = {
    ctrl: PreferencesController;
    /** The embedder model id to show download status for (cloud ids are ignored). */
    modelId: string | null | undefined;
  };

  let { ctrl, modelId }: Props = $props();

  // Only local-registry embedders appear in localEmbedders; cloud ids resolve to undefined and
  // render nothing. Same inline download affordance as the reranker widget.
  const sel = $derived(modelId ? ctrl.localEmbedders.find((m) => m.id === modelId) : undefined);
  const needsDownload = $derived(!!sel && !(sel.downloaded || sel.status === 'ready'));
  const downloading = $derived(
    !!sel && (sel.status === 'downloading' || ctrl.embedderDownloading === sel.id)
  );
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
          <Button variant="outline" size="sm" onclick={() => ctrl.cancelEmbedder(sel.id)}>
            Cancel
          </Button>
        {:else}
          <Button
            variant="outline"
            size="sm"
            disabled={ctrl.busy || ctrl.embedderBusy}
            onclick={() => ctrl.downloadEmbedder(sel.id)}
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
