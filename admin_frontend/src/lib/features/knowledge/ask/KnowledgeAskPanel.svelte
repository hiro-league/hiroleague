<script lang="ts">
  import { BookText, ChevronDown, ChevronUp, Code, Database, ExternalLink, FilterX, LoaderCircle, Search } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import CreatableCategorySelect from '$lib/features/knowledge/CreatableCategorySelect.svelte';
  import CreatableTagsSelect from '$lib/features/knowledge/CreatableTagsSelect.svelte';
  import KnowledgeChunkMarkdownPreview from '$lib/features/knowledge/shared/KnowledgeChunkMarkdownPreview.svelte';
  import { graphRunPageUrl } from '$lib/features/graph-runs/graph-runs-pure';
  import type { KnowledgePageController } from '$lib/features/knowledge/state/knowledge-controller.svelte';
  import {
    chunkTextByteSize,
    formatBytes,
    optionalInt,
    readKnowledgeChunkMarkdownFormat,
    writeKnowledgeChunkMarkdownFormat
  } from '$lib/features/knowledge/shared/knowledge-pure';
  import {
    KNOWLEDGE_FIELD_LABEL,
    KNOWLEDGE_FIELD_LABEL_TEXT,
    KNOWLEDGE_INPUT,
    KNOWLEDGE_INPUT_LG,
    KNOWLEDGE_METADATA_SHELL,
    KNOWLEDGE_SECTION_CARD,
    KNOWLEDGE_SECTION_TITLE,
    KNOWLEDGE_SELECT
  } from '$lib/features/knowledge/shared/knowledge-ui';
  import { cn } from '$lib/utils';

  interface Props {
    ctl: KnowledgePageController;
  }

  let { ctl }: Props = $props();
  const ask = $derived(ctl.ask);
  const options = $derived(ctl.options);

  let chunkMarkdownFormat = $state(readKnowledgeChunkMarkdownFormat());
  let filtersExpanded = $state(true);
</script>

<section class="grid gap-4">
  <div class={KNOWLEDGE_SECTION_CARD}>
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
      <div class="mt-3 flex flex-wrap items-center gap-2 rounded-md border bg-background px-3 py-2 font-sans text-sm">
        <span class="text-muted-foreground">Scoped to document:</span>
        <Badge variant="secondary">{ask.askDocumentScope.title || ask.askDocumentScope.source_uri}</Badge>
        <Button class="h-7 px-2" variant="ghost" onclick={ask.clearAskDocumentScope}>Clear scope</Button>
      </div>
    {/if}

    <div class={cn(KNOWLEDGE_METADATA_SHELL, 'mt-3')}>
      <div class="flex items-center gap-2">
        <Button
          variant="ghost"
          size="icon"
          class="size-7 shrink-0 text-muted-foreground hover:text-foreground"
          type="button"
          aria-expanded={filtersExpanded}
          aria-controls="knowledge-ask-filters-panel"
          aria-label={filtersExpanded ? 'Collapse filters' : 'Expand filters'}
          title={filtersExpanded ? 'Collapse filters' : 'Expand filters'}
          onclick={() => {
            filtersExpanded = !filtersExpanded;
          }}
        >
          {#if filtersExpanded}
            <ChevronUp size={18} strokeWidth={2} aria-hidden="true" />
          {:else}
            <ChevronDown size={18} strokeWidth={2} aria-hidden="true" />
          {/if}
        </Button>
        <div class="font-sans text-sm font-medium">Filters</div>
        <Button
          variant="ghost"
          size="icon"
          class={cn(
            'size-7 shrink-0',
            ask.hasAskFilters
              ? 'text-destructive hover:bg-destructive/10 hover:text-destructive'
              : 'text-muted-foreground'
          )}
          type="button"
          aria-label="Clear filters"
          title="Clear filters"
          disabled={!ask.hasAskFilters}
          onclick={() => ask.clearAskFilters()}
        >
          <FilterX size={16} aria-hidden="true" />
        </Button>
      </div>
      {#if filtersExpanded}
      <div id="knowledge-ask-filters-panel" class="grid gap-3">
        <div class="flex flex-wrap items-end gap-3">
          <label class={KNOWLEDGE_FIELD_LABEL}>
            <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Owner</span>
            <select
              class={cn(KNOWLEDGE_SELECT, 'w-[180px]')}
              bind:value={ask.askOwnerKind}
              onchange={ask.handleAskOwnerKindChange}
            >
              <option value="">Any</option>
              <option value="system">System</option>
              <option value="character">Character</option>
              <option value="user">User</option>
            </select>
          </label>
          {#if ask.askOwnerKind === 'character'}
            <label class={KNOWLEDGE_FIELD_LABEL}>
              <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Character</span>
              <select class={cn(KNOWLEDGE_SELECT, 'w-[220px]')} bind:value={ask.askOwnerId}>
                {#each options.characters as character (character.id)}
                  <option value={String(character.id)}>{character.name} ({character.id})</option>
                {/each}
              </select>
            </label>
          {:else if ask.askOwnerKind === 'user'}
            <label class={KNOWLEDGE_FIELD_LABEL}>
              <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>User</span>
              <select class={cn(KNOWLEDGE_SELECT, 'w-[220px]')} bind:value={ask.askOwnerId}>
                {#each options.users as user (user.id)}
                  <option value={String(user.id)}>{user.name} ({user.id})</option>
                {/each}
              </select>
            </label>
          {/if}
          <label class={KNOWLEDGE_FIELD_LABEL}>
            <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Category</span>
            <CreatableCategorySelect
              bind:value={ask.askCategoryId}
              options={options.topCategories}
              placeholder="Any"
              searchPlaceholder="Search or create category…"
              creating={options.creatingCategory}
              onSelect={() => {
                ask.askSubcategoryId = '';
              }}
              onCreate={(name) => options.upsertCategoryByName(name, null)}
            />
          </label>
          <label class={KNOWLEDGE_FIELD_LABEL}>
            <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Subcategory</span>
            <CreatableCategorySelect
              bind:value={ask.askSubcategoryId}
              options={ask.askSubcategories}
              placeholder="Any"
              searchPlaceholder="Search or create subcategory…"
              disabled={!ask.askCategoryId}
              creating={options.creatingSubcategory}
              onCreate={(name) => options.upsertCategoryByName(name, optionalInt(ask.askCategoryId))}
            />
          </label>
          <label class="grid min-w-[280px] flex-1 gap-1 font-sans text-sm">
            <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Tags</span>
            <CreatableTagsSelect
              bind:selected={ask.askTags}
              options={options.tags}
              creating={options.creatingTag}
              onCreate={options.upsertTag}
            />
          </label>
        </div>
        <div class="flex flex-wrap items-end gap-3">
          <label class={KNOWLEDGE_FIELD_LABEL}>
            <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Top K</span>
            <input
              class={cn(KNOWLEDGE_INPUT, 'w-24')}
              type="number"
              min="1"
              max="100"
              bind:value={ask.askTopK}
            />
          </label>
          <label class={KNOWLEDGE_FIELD_LABEL}>
            <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Min score</span>
            <input
              class={cn(KNOWLEDGE_INPUT, 'w-32')}
              type="number"
              min="0"
              max="1"
              step="0.05"
              bind:value={ask.askMinScore}
            />
          </label>
        </div>
      </div>
      {/if}
    </div>

    {#if ask.answerResult?.no_results}
      <div class="mt-4 rounded-md border px-3 py-8 text-center font-sans text-sm text-muted-foreground">
        No sources matched. Relax filters or lower the minimum score.
      </div>
    {:else if ask.answerResult}
      <article class="mt-4 grid gap-3 rounded-md border bg-background p-4">
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
      <div class="mt-4 rounded-md border px-3 py-8 text-center font-sans text-sm text-muted-foreground">
        Ask a question to retrieve cited sources.
      </div>
    {/if}
  </div>

  {#if ask.answerResult && !ask.answerResult.no_results && ask.answerResult.sources.length > 0}
    <div class={KNOWLEDGE_SECTION_CARD}>
      <div class="mb-3 flex items-center gap-2">
        <Database size={17} class="shrink-0 text-muted-foreground" />
        <h3 class={KNOWLEDGE_SECTION_TITLE}>Chunk Results</h3>
        <Button
          variant="ghost"
          size="icon"
          class="ml-auto size-8 shrink-0 text-muted-foreground hover:text-foreground"
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
        <Badge class="shrink-0" variant="outline">{ask.answerResult.sources.length}</Badge>
      </div>
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
    </div>
  {/if}
</section>
