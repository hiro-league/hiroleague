<script lang="ts">
  import Button from '$lib/components/ui/button.svelte';
  import SectionCardMuted from '$lib/components/page/SectionCardMuted.svelte';
  import type { PreferencesController } from '$lib/features/preferences/state/preferences-controller.svelte';
  import { PREFERENCES_SECTION_BODY_IDS } from '$lib/features/preferences/shared/preferences-section-a11y';
  import PrefModelPicker from '$lib/features/preferences/widgets/PrefModelPicker.svelte';
  import PrefToggleField from '$lib/features/preferences/widgets/PrefToggleField.svelte';

  type Props = {
    ctrl: PreferencesController;
  };

  let { ctrl }: Props = $props();
</script>

{#if ctrl.draft}
  <SectionCardMuted
    title="Reranker"
    description="Optional cross-encoder that reorders retrieved candidates by relevance before answering (precision step). Default off. Cloud models need a provider key; local models must be downloaded first. Switching is a hot swap — no re-ingest."
    collapsible
    bodyId={PREFERENCES_SECTION_BODY_IDS.knowledgeReranker}
  >
    <PrefToggleField
      {ctrl}
      path="knowledge.retrieval.reranker.enabled"
      label="Enable reranking"
      bind:checked={ctrl.draft.knowledge.retrieval.reranker.enabled}
    />
    <PrefModelPicker
      {ctrl}
      kind="rerank"
      path="knowledge.retrieval.reranker.model_id"
      embedded
      label="Reranker model"
      selectedId={ctrl.draft.knowledge.retrieval.reranker.model_id}
    />

    {#if ctrl.draft.knowledge.retrieval.reranker.model_id}
      {@const sel = ctrl.localRerankers.find(
        (m) => m.id === ctrl.draft?.knowledge.retrieval.reranker.model_id
      )}
      {#if sel && !(sel.downloaded || sel.status === 'ready')}
        {@const downloading = sel.status === 'downloading' || ctrl.rerankerDownloading === sel.id}
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
                <Button variant="outline" size="sm" onclick={() => ctrl.cancelReranker(sel.id)}>
                  Cancel
                </Button>
              {:else}
                <Button
                  variant="outline"
                  size="sm"
                  disabled={ctrl.busy || ctrl.rerankerBusy}
                  onclick={() => ctrl.downloadReranker(sel.id)}
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
    {/if}

    <p class="text-xs text-muted-foreground">
      Cloud scores are calibrated <code>[0,1]</code>; local cross-encoder scores are
      sigmoid-normalized. A normalized <code>relevance</code> is emitted whether reranking is on
      (reranker score) or off (retrieval rank), so downstream ranking stays consistent.
    </p>
  </SectionCardMuted>
{/if}
