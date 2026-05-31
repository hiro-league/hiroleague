<script lang="ts">
  import { FilterX } from '@lucide/svelte';
  import AdminFilterBar from '$lib/components/page/table/AdminFilterBar.svelte';
  import AdminFilterBarSelect from '$lib/components/page/table/AdminFilterBarSelect.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import CreatableCategorySelect from '$lib/features/knowledge/CreatableCategorySelect.svelte';
  import CreatableTagsSelect from '$lib/features/knowledge/CreatableTagsSelect.svelte';
  import type { KnowledgeAskModel } from '$lib/features/knowledge/state/knowledge-ask.svelte';
  import type { KnowledgeOptionsModel } from '$lib/features/knowledge/state/knowledge-options.svelte';
  import { optionalInt } from '$lib/features/knowledge/shared/knowledge-pure';
  import { KNOWLEDGE_INPUT } from '$lib/features/knowledge/shared/knowledge-ui';
  import { cn } from '$lib/utils';

  type Props = {
    ask: KnowledgeAskModel;
    options: KnowledgeOptionsModel;
  };

  let { ask, options }: Props = $props();

  const characterFilterOptions = $derived(
    options.characters.map((character) => ({
      value: String(character.id),
      label: `${character.name} (${character.id})`
    }))
  );
  const userFilterOptions = $derived(
    options.users.map((user) => ({
      value: String(user.id),
      label: `${user.name} (${user.id})`
    }))
  );
</script>

<AdminFilterBar class="flex-wrap items-end">
  <AdminFilterBarSelect
    label="Owner"
    bind:value={ask.askOwnerKind}
    placeholder="Any"
    class="w-[9rem] shrink-0"
    onValueChange={() => ask.handleAskOwnerKindChange()}
    options={[
      { value: 'system', label: 'System' },
      { value: 'character', label: 'Character' },
      { value: 'user', label: 'User' }
    ]}
  />
  {#if ask.askOwnerKind === 'character'}
    <AdminFilterBarSelect
      label="Character"
      bind:value={ask.askOwnerId}
      class="w-[11rem] shrink-0"
      options={characterFilterOptions}
    />
  {:else if ask.askOwnerKind === 'user'}
    <AdminFilterBarSelect
      label="User"
      bind:value={ask.askOwnerId}
      class="w-[11rem] shrink-0"
      options={userFilterOptions}
    />
  {/if}
  <FormField label="Category" class="w-[11rem] shrink-0">
    <CreatableCategorySelect
      bind:value={ask.askCategoryId}
      options={options.topCategories}
      placeholder="Any"
      searchPlaceholder="Search or create category…"
      creating={options.creatingCategory}
      class="w-full"
      onSelect={() => {
        ask.askSubcategoryId = '';
      }}
      onCreate={(name) => options.upsertCategoryByName(name, null)}
    />
  </FormField>
  <FormField label="Subcategory" class="w-[11rem] shrink-0">
    <CreatableCategorySelect
      bind:value={ask.askSubcategoryId}
      options={ask.askSubcategories}
      placeholder="Any"
      searchPlaceholder="Search or create subcategory…"
      disabled={!ask.askCategoryId}
      creating={options.creatingSubcategory}
      class="w-full"
      onCreate={(name) => options.upsertCategoryByName(name, optionalInt(ask.askCategoryId))}
    />
  </FormField>
  <label class="grid w-[12rem] shrink-0 gap-1.5 text-left">
    <span class="font-sans text-sm font-semibold leading-snug text-muted-foreground">Tags</span>
    <CreatableTagsSelect
      bind:selected={ask.askTags}
      options={options.tags}
      creating={options.creatingTag}
      class="w-full"
      onCreate={options.upsertTag}
    />
  </label>
  <FormField label="Top K" class="w-[5.5rem] shrink-0">
    <input
      class={cn(KNOWLEDGE_INPUT, 'w-full')}
      type="number"
      min="1"
      max="100"
      bind:value={ask.askTopK}
    />
  </FormField>
  <FormField label="Min score" class="w-[6.5rem] shrink-0">
    <input
      class={cn(KNOWLEDGE_INPUT, 'w-full')}
      type="number"
      min="0"
      max="1"
      step="0.05"
      bind:value={ask.askMinScore}
    />
  </FormField>
  <label
    class="flex shrink-0 cursor-pointer select-none items-center gap-2 self-end pb-2"
    title="Rewrite the query with an LLM before retrieval: normalize wording and extract literal keywords (one extra model call)"
  >
    <input type="checkbox" class="size-4" bind:checked={ask.askRewrite} />
    <span class="text-sm text-muted-foreground">Rewrite</span>
  </label>
  <label
    class="flex shrink-0 cursor-pointer select-none items-center gap-2 self-end pb-2"
    title="Show match type, per-branch cosine/BM25 scores, and matched terms for each result (extra query work)"
  >
    <input type="checkbox" class="size-4" bind:checked={ask.askExplain} />
    <span class="text-sm text-muted-foreground">Explain</span>
  </label>
  <!-- L3 (Phase 5d) — Graph retrieval mode. off = flat (today). on = graph_expand focuses
       Qdrant on chunks linked to query entities. compare = both legs side-by-side.
       Persists across reloads via knowledgeAskGraphMode preference. -->
  <fieldset
    class="flex shrink-0 items-center gap-1 self-end pb-2"
    title="Graph mode: off (flat) · on (graph-augmented) · compare (both side-by-side). Requires Rewrite to extract query entities."
  >
    <legend class="sr-only">Graph retrieval mode</legend>
    <span class="mr-1 text-sm text-muted-foreground">Graph</span>
    {#each ['off', 'on', 'compare'] as mode (mode)}
      <button
        type="button"
        class="rounded-md border px-2 py-1 font-sans text-xs capitalize transition-colors {ask.graphMode === mode
          ? 'border-primary bg-primary/10 text-foreground'
          : 'border-input bg-background text-muted-foreground hover:text-foreground'}"
        aria-pressed={ask.graphMode === mode}
        onclick={() => ask.setGraphMode(mode as 'off' | 'on' | 'compare')}
      >
        {mode}
      </button>
    {/each}
  </fieldset>
  <div class="flex items-end">
    <Button variant="outline" disabled={!ask.hasAskFilters} onclick={() => ask.clearAskFilters()}>
      <FilterX size={15} /> Clear
    </Button>
  </div>
</AdminFilterBar>
