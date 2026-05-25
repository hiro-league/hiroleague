<script lang="ts">
  import { BookText, Code, ExternalLink, LoaderCircle, Search } from '@lucide/svelte';
  import AdminPageStickyToolbar from '$lib/components/page/AdminPageStickyToolbar.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import KnowledgeAskFilterBar from '$lib/features/knowledge/ask/KnowledgeAskFilterBar.svelte';
  import KnowledgeCollapsibleSectionCard from '$lib/features/knowledge/shared/KnowledgeCollapsibleSectionCard.svelte';
  import KnowledgeChunkMarkdownPreview from '$lib/features/knowledge/shared/KnowledgeChunkMarkdownPreview.svelte';
  import { graphRunPageUrl } from '$lib/features/graph-runs/graph-runs-pure';
  import type { KnowledgePageController } from '$lib/features/knowledge/state/knowledge-controller.svelte';
  import {
    chunkTextByteSize,
    formatBytes,
    readKnowledgeChunkMarkdownFormat,
    writeKnowledgeChunkMarkdownFormat
  } from '$lib/features/knowledge/shared/knowledge-pure';
  import {
    KNOWLEDGE_ASK_CHUNK_RESULTS_BODY_ID,
    KNOWLEDGE_ASK_QUESTION_BODY_ID,
    KNOWLEDGE_FIELD_LABEL_TEXT,
    KNOWLEDGE_INPUT_LG
  } from '$lib/features/knowledge/shared/knowledge-ui';

  interface Props {
    ctl: KnowledgePageController;
  }

  let { ctl }: Props = $props();
  const ask = $derived(ctl.ask);
  const options = $derived(ctl.options);

  let chunkMarkdownFormat = $state(readKnowledgeChunkMarkdownFormat());

  const questionHeaderSummary = $derived(
    ask.searching ? 'Searching…' : ask.answerResult?.no_results ? 'No sources matched' : ask.answerResult ? 'Answer ready' : ''
  );
</script>

<section class="grid gap-4">
  <AdminPageStickyToolbar>
    <KnowledgeAskFilterBar {ask} {options} />
  </AdminPageStickyToolbar>

  <KnowledgeCollapsibleSectionCard
    title="Question"
    bodyId={KNOWLEDGE_ASK_QUESTION_BODY_ID}
    defaultExpanded={true}
    summary={questionHeaderSummary}
  >
    <div class="flex flex-wrap items-end gap-3">
      <label class="grid min-w-[320px] flex-1 gap-1 font-sans text-sm">
        <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Question</span>
        <input
          class={KNOWLEDGE_INPUT_LG}
          bind:this={ask.queryInputEl}
          bind:value={ask.query}
          onkeydown={(event) => {
            if (event.key === 'Enter') void ask.runSearch();
          }}
        />
      </label>
      <Button onclick={() => void ask.runSearch()} disabled={ask.searching || !ask.query.trim()}>
        {#if ask.searching}
          <LoaderCircle size={16} class="animate-spin" />
        {:else}
          <Search size={16} />
        {/if}
        Ask
      </Button>
    </div>

    {#if ask.askDocumentScope}
      <div class="flex flex-wrap items-center gap-2 rounded-md border bg-background px-3 py-2 font-sans text-sm">
        <span class="text-muted-foreground">Scoped to document:</span>
        <Badge variant="secondary">{ask.askDocumentScope.title || ask.askDocumentScope.source_uri}</Badge>
        <Button class="h-7 px-2" variant="ghost" onclick={ask.clearAskDocumentScope}>Clear scope</Button>
      </div>
    {/if}

    {#if ask.answerResult?.no_results}
      <div class="rounded-md border px-3 py-8 text-center font-sans text-sm text-muted-foreground">
        No sources matched. Relax filters or lower the minimum score.
      </div>
    {:else if ask.answerResult}
      <article class="grid gap-3 rounded-md border bg-background p-4">
        <div class="flex flex-wrap items-center gap-2">
          <Badge variant="outline">{ask.answerResult.elapsed_ms}ms</Badge>
          {#if ask.answerResult.model_id}<Badge variant="secondary">{ask.answerResult.model_id}</Badge>{/if}
          {#if ask.answerResult.usage?.usage_available}
            <Badge variant="outline">
              {(ask.answerResult.usage.input_tokens ?? ask.answerResult.usage.estimated_input_tokens ?? 0)} in /
              {(ask.answerResult.usage.output_tokens ?? 0)} out
            </Badge>
          {/if}
          {#if ask.answerResult.run_id}
            <a
              class="inline-flex items-center gap-1 rounded-md border px-2 py-1 font-sans text-xs text-primary hover:bg-primary/5"
              href={graphRunPageUrl(ask.answerResult.run_id)}
              title={ask.answerResult.run_id}
            >
              <ExternalLink size={12} aria-hidden="true" />
              Graph run
            </a>
          {/if}
          <Button
            class="ml-auto h-8"
            variant="outline"
            onclick={() => navigator.clipboard?.writeText(ask.answerResult?.answer ?? '')}
          >
            Copy answer
          </Button>
        </div>
        <p class="whitespace-pre-wrap font-sans text-sm leading-6">{ask.answerResult.answer}</p>
      </article>
    {:else}
      <div class="rounded-md border px-3 py-8 text-center font-sans text-sm text-muted-foreground">
        Ask a question to retrieve cited sources.
      </div>
    {/if}
  </KnowledgeCollapsibleSectionCard>

  {#if ask.answerResult && !ask.answerResult.no_results && ask.answerResult.sources.length > 0}
    <KnowledgeCollapsibleSectionCard
      title="Chunk Results"
      bodyId={KNOWLEDGE_ASK_CHUNK_RESULTS_BODY_ID}
      defaultExpanded={false}
      summary={`${ask.answerResult.sources.length} chunks`}
    >
      {#snippet headerActions()}
        <Button
          variant="ghost"
          size="icon"
          class="size-8 shrink-0 text-muted-foreground hover:text-foreground"
          type="button"
          aria-label={chunkMarkdownFormat ? 'Show raw chunk text' : 'Show formatted markdown'}
          aria-pressed={chunkMarkdownFormat}
          title={chunkMarkdownFormat ? 'Formatted markdown — click for raw text' : 'Raw text — click for formatted markdown'}
          onclick={() => {
            chunkMarkdownFormat = !chunkMarkdownFormat;
            writeKnowledgeChunkMarkdownFormat(chunkMarkdownFormat);
          }}
        >
          {#if chunkMarkdownFormat}
            <BookText size={16} aria-hidden="true" />
          {:else}
            <Code size={16} aria-hidden="true" />
          {/if}
        </Button>
      {/snippet}
      <div class="rounded-md border">
        {#each ask.answerResult.sources as source (source.point_id)}
          <article class="grid gap-2 border-t px-3 py-3 first:border-t-0">
            <div class="flex min-w-0 items-center gap-2">
              <Badge class="shrink-0 rounded-md font-mono tabular-nums" variant="secondary">#{source.ref}</Badge>
              <span class="min-w-0 truncate font-sans text-sm font-medium">{source.title}</span>
              {#if source.heading_path}
                <span class="min-w-0 truncate font-sans text-xs text-muted-foreground">{source.heading_path}</span>
              {/if}
              <Badge class="ml-auto shrink-0 font-mono tabular-nums" variant="outline">
                {source.score.toFixed(3)}
              </Badge>
              <Badge class="shrink-0 font-mono tabular-nums" variant="outline">
                {formatBytes(chunkTextByteSize(source.text))}
              </Badge>
            </div>
            {#if chunkMarkdownFormat}
              <KnowledgeChunkMarkdownPreview markdown={source.text} class="text-muted-foreground" />
            {:else}
              <p class="whitespace-pre-wrap font-sans text-sm leading-6 text-muted-foreground">{source.text}</p>
            {/if}
          </article>
        {/each}
      </div>
    </KnowledgeCollapsibleSectionCard>
  {/if}
</section>
