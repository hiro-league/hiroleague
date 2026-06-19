<script lang="ts">
  import { base } from '$app/paths';
  import { Check, ChevronRight, ExternalLink, LoaderCircle } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import CreatableCategorySelect from '$lib/features/knowledge/shared/CreatableCategorySelect.svelte';
  import CreatableTagsSelect from '$lib/features/knowledge/shared/CreatableTagsSelect.svelte';
  import type { KnowledgePageController } from '$lib/features/knowledge/state/knowledge-controller.svelte';
  import type { KnowledgeIngestModel } from '$lib/features/knowledge/state/knowledge-ingest.svelte';
  import type { KnowledgeOptionsModel } from '$lib/features/knowledge/state/knowledge-options.svelte';
  import { formatJobTotalsSummary, jobElapsed, KNOWLEDGE_BROWSE_HREF, optionalInt } from '$lib/features/knowledge/shared/knowledge-pure';
  import {
    KNOWLEDGE_FIELD_LABEL,
    KNOWLEDGE_FIELD_LABEL_TEXT,
    KNOWLEDGE_METADATA_SHELL,
    KNOWLEDGE_SECTION_CARD,
    KNOWLEDGE_SECTION_TITLE,
    KNOWLEDGE_SELECT
  } from '$lib/features/knowledge/shared/knowledge-ui';
  import InlineDestructiveAlert from '$lib/ui/InlineDestructiveAlert.svelte';
  import { cn } from '$lib/utils';

  type Props = {
    ctl: KnowledgePageController;
    ingest: KnowledgeIngestModel;
    options: KnowledgeOptionsModel;
    expanded?: boolean;
    headerSummary: string | null;
  };

  let { ctl, ingest, options, expanded = $bindable(), headerSummary }: Props = $props();

  const INGEST_BODY_ID = 'knowledge-ingest-section';
</script>

<section class={KNOWLEDGE_SECTION_CARD}>
  <div class="grid gap-3">
    <div class="flex items-start justify-between gap-2">
      <button
        type="button"
        class="flex min-w-0 flex-1 items-start gap-2 rounded-md py-0.5 text-left outline-none transition hover:bg-muted/30 focus-visible:ring-2 focus-visible:ring-ring"
        aria-expanded={expanded}
        aria-controls={INGEST_BODY_ID}
        onclick={() => {
          expanded = !expanded;
        }}
      >
        <ChevronRight
          size={18}
          class={cn(
            'mt-0.5 shrink-0 text-muted-foreground transition-transform duration-150',
            expanded && 'rotate-90'
          )}
          aria-hidden="true"
        />
        <span class={KNOWLEDGE_SECTION_TITLE}>Ingest</span>
      </button>
      {#if headerSummary}
        <span class="shrink-0 text-right font-sans text-xs text-muted-foreground">{headerSummary}</span>
      {/if}
    </div>
    <div id={INGEST_BODY_ID} class="grid gap-3" hidden={!expanded}>
      <div class={KNOWLEDGE_METADATA_SHELL}>
        <div class="font-sans text-sm font-medium">Ingest metadata</div>
        <div class="grid gap-3">
          <div class="flex flex-wrap items-end gap-3">
            <label class={KNOWLEDGE_FIELD_LABEL}>
              <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Owner</span>
              <select class={cn(KNOWLEDGE_SELECT, 'w-[180px]')} bind:value={ingest.ownerKind} onchange={ingest.handleOwnerKindChange}>
                <option value="system">System</option>
                <option value="character">Character</option>
                <option value="user">User</option>
              </select>
            </label>
            {#if ingest.ownerKind === 'character'}
              <label class={KNOWLEDGE_FIELD_LABEL}>
                <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Character</span>
                <select class={cn(KNOWLEDGE_SELECT, 'w-[220px]')} bind:value={ingest.ownerId}>
                  {#each options.characters as character (character.id)}
                    <option value={String(character.id)}>{character.name} ({character.id})</option>
                  {/each}
                </select>
              </label>
            {:else if ingest.ownerKind === 'user'}
              <label class={KNOWLEDGE_FIELD_LABEL}>
                <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>User</span>
                <select class={cn(KNOWLEDGE_SELECT, 'w-[220px]')} bind:value={ingest.ownerId}>
                  {#each options.users as user (user.id)}
                    <option value={String(user.id)}>{user.name} ({user.id})</option>
                  {/each}
                </select>
              </label>
            {/if}
            <label class={KNOWLEDGE_FIELD_LABEL}>
              <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Category</span>
              <CreatableCategorySelect
                bind:value={ingest.categoryId}
                options={options.topCategories}
                placeholder="None"
                searchPlaceholder="Search or create category…"
                creating={options.creatingCategory}
                onSelect={() => {
                  ingest.subcategoryId = '';
                }}
                onCreate={(name) => options.upsertCategoryByName(name, null)}
              />
            </label>
            <label class={KNOWLEDGE_FIELD_LABEL}>
              <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Subcategory</span>
              <CreatableCategorySelect
                bind:value={ingest.subcategoryId}
                options={ingest.subcategories}
                placeholder="None"
                searchPlaceholder="Search or create subcategory…"
                disabled={!ingest.categoryId}
                creating={options.creatingSubcategory}
                onCreate={(name) => options.upsertCategoryByName(name, optionalInt(ingest.categoryId))}
              />
            </label>
            <label class="grid min-w-[280px] flex-1 gap-1 font-sans text-sm">
              <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Tags</span>
              <CreatableTagsSelect
                bind:selected={ingest.ingestTags}
                options={options.tags}
                creating={options.creatingTag}
                onCreate={options.upsertTag}
              />
            </label>
            <!-- L3 (Phase 5f) — "Also build entity graph" opt-in. When checked
                 and an ingest succeeds, the controller auto-fires the batch
                 graph-ingest over the newly-ingested document_ids. Preference
                 persists across reloads. -->
            <label
              class="flex shrink-0 cursor-pointer select-none items-center gap-2 self-end pb-2"
              title="After ingest, run LLM entity extraction over the new chunks and write nodes + relations into the L3 graph (one extra LLM call per chunk; costs more)"
            >
              <input
                type="checkbox"
                class="size-4"
                checked={ingest.buildGraphAfter}
                onchange={(e) => ingest.setBuildGraphAfter((e.currentTarget as HTMLInputElement).checked)}
                disabled={ingest.ingesting}
              />
              <span class="text-sm text-muted-foreground">Also build entity graph (L3)</span>
            </label>
            <Button
              variant="outline"
              onclick={() => void ingest.ingestSelected()}
              disabled={ingest.ingesting || ingest.selectedPaths.length === 0 || (ingest.ownerKind !== 'system' && !ingest.ownerId)}
            >
              {#if ingest.ingesting}
                <LoaderCircle size={16} class="animate-spin" />
              {:else}
                <Check size={16} />
              {/if}
              Ingest {ingest.selectedPaths.length}
            </Button>
          </div>
        </div>
      </div>

      {#if ingest.job}
        <div class="grid gap-2 rounded-md border bg-background p-3 font-sans text-sm">
          <div class="flex flex-wrap items-center gap-2">
            <Badge variant={ingest.job.status === 'completed' ? 'success' : ingest.job.status === 'failed' ? 'destructive' : 'outline'}>
              {ingest.job.status}
            </Badge>
            <span class="text-muted-foreground">
              {formatJobTotalsSummary(ingest.job.totals)}
            </span>
            {#if ingest.currentJobRecord}
              <span class="text-xs text-muted-foreground">elapsed {jobElapsed(ingest.currentJobRecord.created_at)}</span>
            {/if}
            <span class="ml-auto text-xs text-muted-foreground">{ingest.jobDone}/{ingest.job.totals.requested ?? 0} files</span>
            {#if ingest.job.status === 'running'}
              <Button class="h-8" type="button" variant="outline" disabled title="Cancellation is documented but not implemented yet.">
                Cancel
              </Button>
            {:else if ingest.job.status === 'completed'}
              <a
                class="inline-flex h-8 items-center gap-1 rounded-md border px-2 py-1 font-sans text-xs text-primary hover:bg-primary/5"
                href={`${base}${KNOWLEDGE_BROWSE_HREF}`}
                onclick={(event) => {
                  event.preventDefault();
                  void ctl.setActiveTab('browse');
                }}
              >
                View documents
                <ExternalLink size={12} aria-hidden="true" />
              </a>
            {/if}
          </div>
          <div class="h-2 overflow-hidden rounded-full bg-muted">
            <div class="h-full bg-primary transition-all" style={`width: ${ingest.jobPercent}%`}></div>
          </div>
          {#if ingest.job.in_flight?.length}
            <div class="truncate font-sans text-xs text-muted-foreground" title={ingest.job.in_flight.join(', ')}>
              Processing {ingest.job.in_flight.length} file(s): {ingest.job.in_flight.join(', ')}
            </div>
          {/if}
          <!-- L3 (Phase 5f) — Graph-build status after the ingest job. Surfaces
               inside the same job card so it's visually adjacent (one outcome
               chain: ingest → graph build). Idle = checkbox was off OR no
               trigger yet; running = the batch HTTP call is in flight (no SSE
               stream for graph build yet, so this is a single spinner row). -->
          {#if ingest.graphBuildStatus !== 'idle' || ingest.graphBuildError}
            <div class="flex flex-wrap items-center gap-2 rounded-md border border-dashed bg-muted/20 px-2 py-1.5 text-xs">
              <span class="font-medium text-muted-foreground">Graph build:</span>
              {#if ingest.graphBuildStatus === 'running'}
                <LoaderCircle size={12} class="animate-spin" aria-hidden="true" />
                <span>extracting entities from new chunks…</span>
              {:else if ingest.graphBuildStatus === 'completed' && ingest.graphBuildResult}
                {@const t = ingest.graphBuildResult.totals}
                <Badge variant="success" class="font-mono text-[11px]">done</Badge>
                <span class="text-muted-foreground">
                  {ingest.graphBuildResult.document_count} doc(s)
                  · entities created {t.entities_created ?? 0}, linked {(t.entities_linked_exact ?? 0) + (t.entities_linked_fuzzy ?? 0) + (t.entities_linked_llm ?? 0)}
                  · edges {t.edges_written ?? 0}
                  · tokens {t.total_input_tokens ?? 0}i/{t.total_output_tokens ?? 0}o
                </span>
                <Button variant="ghost" class="ml-auto h-6 px-2 text-xs" onclick={ingest.clearGraphBuildResult}>Dismiss</Button>
              {:else if ingest.graphBuildStatus === 'failed'}
                <Badge variant="destructive" class="font-mono text-[11px]">failed</Badge>
                <span class="text-destructive">{ingest.graphBuildError}</span>
                <Button variant="ghost" class="ml-auto h-6 px-2 text-xs" onclick={ingest.clearGraphBuildResult}>Dismiss</Button>
              {/if}
            </div>
          {/if}
          {#if Object.keys(ingest.job.errors).length > 0}
            <details class="text-xs">
              <summary class="text-destructive">View errors</summary>
              <InlineDestructiveAlert
                class="mt-2 whitespace-pre-wrap font-mono text-xs"
                message={JSON.stringify(ingest.job.errors, null, 2)}
              />
            </details>
          {/if}
        </div>
      {/if}
    </div>
  </div>
</section>
