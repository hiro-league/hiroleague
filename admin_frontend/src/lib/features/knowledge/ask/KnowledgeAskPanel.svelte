<script lang="ts">
  import { FileText, LoaderCircle, Search } from '@lucide/svelte';
  import Button from '$lib/components/ui/button.svelte';
  import Badge from '$lib/components/ui/badge.svelte';
  import type { KnowledgePageController } from '$lib/features/knowledge/state/knowledge-controller.svelte';
  import {
    KNOWLEDGE_FIELD_LABEL,
    KNOWLEDGE_FIELD_LABEL_TEXT,
    KNOWLEDGE_INPUT_LG,
    KNOWLEDGE_METADATA_SHELL,
    KNOWLEDGE_SECTION_CARD,
    KNOWLEDGE_SELECT_LG
  } from '$lib/features/knowledge/shared/knowledge-ui';
  import { cn } from '$lib/utils';

  interface Props {
    ctl: KnowledgePageController;
  }

  let { ctl }: Props = $props();
  const ask = $derived(ctl.ask);
  const options = $derived(ctl.options);
</script>

<section class={cn('grid gap-4', KNOWLEDGE_SECTION_CARD)}>
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
    <label class="grid w-24 gap-1 font-sans text-sm">
      <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Top K</span>
      <input class={KNOWLEDGE_INPUT_LG} type="number" min="1" max="100" bind:value={ask.askTopK} />
    </label>
    <label class="grid w-32 gap-1 font-sans text-sm">
      <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Min score</span>
      <input class={KNOWLEDGE_INPUT_LG} type="number" min="0" max="1" step="0.05" bind:value={ask.askMinScore} />
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
  <details class={KNOWLEDGE_METADATA_SHELL}>
    <summary class="cursor-pointer font-sans text-sm font-medium">Filters</summary>
    <div class="mt-3 grid gap-3 md:grid-cols-3 xl:grid-cols-6">
      <label class={KNOWLEDGE_FIELD_LABEL}>
        <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Owner</span>
        <select class={KNOWLEDGE_SELECT_LG} bind:value={ask.askOwnerKind}>
          <option value="">Any</option>
          <option value="system">System</option>
          <option value="character">Character</option>
          <option value="user">User</option>
        </select>
      </label>
      <label class={KNOWLEDGE_FIELD_LABEL}>
        <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Owner id</span>
        <input class={KNOWLEDGE_INPUT_LG} bind:value={ask.askOwnerId} placeholder="optional" />
      </label>
      <label class={KNOWLEDGE_FIELD_LABEL}>
        <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Category</span>
        <select
          class={KNOWLEDGE_SELECT_LG}
          bind:value={ask.askCategoryId}
          onchange={() => (ask.askSubcategoryId = '')}
        >
          <option value="">Any</option>
          {#each options.topCategories as category (category.id)}
            <option value={String(category.id)}>{category.name}</option>
          {/each}
        </select>
      </label>
      <label class={KNOWLEDGE_FIELD_LABEL}>
        <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Subcategory</span>
        <select class={KNOWLEDGE_SELECT_LG} bind:value={ask.askSubcategoryId} disabled={!ask.askCategoryId}>
          <option value="">Any</option>
          {#each ask.askSubcategories as category (category.id)}
            <option value={String(category.id)}>{category.name}</option>
          {/each}
        </select>
      </label>
      <label class="grid gap-1 font-sans text-sm xl:col-span-2">
        <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Tags</span>
        <input class={KNOWLEDGE_INPUT_LG} bind:value={ask.askTagsText} placeholder="comma separated" />
      </label>
    </div>
  </details>
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
        <Button class="ml-auto h-8" variant="outline" onclick={() => navigator.clipboard?.writeText(ask.answerResult?.answer ?? '')}>
          Copy answer
        </Button>
      </div>
      <p class="whitespace-pre-wrap font-sans text-sm leading-6">{ask.answerResult.answer}</p>
    </article>
    <div class="grid gap-2">
      {#each ask.answerResult.sources as source (source.point_id)}
        <button
          class="grid gap-2 rounded-md border bg-background p-3 text-left transition-colors hover:border-primary/40"
          type="button"
          onclick={() => ctl.openBrowseForDocument(source.document_id)}
        >
          <div class="flex items-center gap-2">
            <FileText size={16} />
            <strong class="min-w-0 truncate font-sans text-sm">[{source.ref}] {source.title}</strong>
            <Badge class="ml-auto" variant="outline">{source.score.toFixed(3)}</Badge>
          </div>
          {#if source.heading_path}
            <div class="truncate font-sans text-xs text-muted-foreground">{source.heading_path}</div>
          {/if}
          <p class="line-clamp-3 font-sans text-sm text-muted-foreground">{source.text}</p>
        </button>
      {/each}
    </div>
  {:else}
    <div class="rounded-md border px-3 py-8 text-center font-sans text-sm text-muted-foreground">
      Ask a question to retrieve cited sources.
    </div>
  {/if}
</section>
