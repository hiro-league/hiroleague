<script lang="ts">
  import { FilterX } from '@lucide/svelte';
  import FilterBar from '$kit/ui/filter-bar.svelte';
  import FilterSelect from '$kit/ui/filter-select.svelte';
  import { Button } from '$kit/components/ui/button/index.js';
  import { Checkbox } from '$kit/components/ui/checkbox/index.js';
  import Field from '$kit/ui/field.svelte';
  import { Input } from '$kit/components/ui/input/index.js';
  import CreatableCategorySelect from '$lib/features/knowledge/shared/CreatableCategorySelect.svelte';
  import CreatableTagsSelect from '$lib/features/knowledge/shared/CreatableTagsSelect.svelte';
  import type { KnowledgeAskModel } from '$lib/features/knowledge/state/knowledge-ask.svelte';
  import type { KnowledgeOptionsModel } from '$lib/features/knowledge/state/knowledge-options.svelte';
  import { optionalInt } from '$lib/features/knowledge/shared/knowledge-pure';

  type Props = {
    ask: KnowledgeAskModel;
    options: KnowledgeOptionsModel;
  };

  let { ask, options }: Props = $props();
  const uid = $props.id();

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

<FilterBar class="flex-wrap items-end">
  <FilterSelect
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
    <FilterSelect
      label="Character"
      bind:value={ask.askOwnerId}
      class="w-[11rem] shrink-0"
      options={characterFilterOptions}
    />
  {:else if ask.askOwnerKind === 'user'}
    <FilterSelect
      label="User"
      bind:value={ask.askOwnerId}
      class="w-[11rem] shrink-0"
      options={userFilterOptions}
    />
  {/if}
  <Field label="Category" for="{uid}-category" class="w-[11rem] shrink-0">
    <CreatableCategorySelect
      id="{uid}-category"
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
  </Field>
  <Field label="Subcategory" for="{uid}-subcategory" class="w-[11rem] shrink-0">
    <CreatableCategorySelect
      id="{uid}-subcategory"
      bind:value={ask.askSubcategoryId}
      options={ask.askSubcategories}
      placeholder="Any"
      searchPlaceholder="Search or create subcategory…"
      disabled={!ask.askCategoryId}
      creating={options.creatingSubcategory}
      class="w-full"
      onCreate={(name) => options.upsertCategoryByName(name, optionalInt(ask.askCategoryId))}
    />
  </Field>
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
  <Field label="Top K" for="{uid}-topk" class="w-[5.5rem] shrink-0">
    <Input
      id="{uid}-topk"
      type="number"
      min="1"
      max="100"
      bind:value={ask.askTopK}
    />
  </Field>
  <Field label="Min score" for="{uid}-minscore" class="w-[6.5rem] shrink-0">
    <Input
      id="{uid}-minscore"
      type="number"
      min="0"
      max="1"
      step="0.05"
      bind:value={ask.askMinScore}
    />
  </Field>
  <label
    class="flex shrink-0 cursor-pointer select-none items-center gap-2 self-end pb-2"
    title="Rewrite the query with an LLM before retrieval: normalize wording and extract literal keywords (one extra model call)"
  >
    <Checkbox bind:checked={ask.askRewrite} />
    <span class="text-sm text-muted-foreground">Rewrite</span>
  </label>
  <label
    class="flex shrink-0 cursor-pointer select-none items-center gap-2 self-end pb-2"
    title="Show match type, per-branch cosine/BM25 scores, and matched terms for each result (extra query work)"
  >
    <Checkbox bind:checked={ask.askExplain} />
    <span class="text-sm text-muted-foreground">Explain</span>
  </label>
  <!-- L3 (Phase 5d) — Graph retrieval mode. off = flat (today). on = graph_expand focuses
       Qdrant on chunks linked to query entities. compare = both legs side-by-side.
       Persists across reloads via knowledgeAskGraphMode preference.
       Changed from a button group to a top-down label + dropdown to match the other filters. -->
  <FilterSelect
    label="Graph"
    value={ask.graphMode}
    class="w-[9rem] shrink-0"
    onValueChange={(value) => ask.setGraphMode(value as 'off' | 'on' | 'compare')}
    options={[
      { value: 'off', label: 'Off' },
      { value: 'on', label: 'On' },
      { value: 'compare', label: 'Compare' }
    ]}
  />
  <!-- Per-query temporal override (§7): overrides the admin temporal_default for THIS
       query only. Relevant only when the graph leg runs (mode on/compare). -->
  {#if ask.graphMode !== 'off'}
    <FilterSelect
      label="Time"
      value={ask.graphTemporal}
      class="w-[9rem] shrink-0"
      onValueChange={(value) => ask.setGraphTemporal(value as 'default' | 'current' | 'all')}
      options={[
        { value: 'default', label: 'Default' },
        { value: 'current', label: 'Current' },
        { value: 'all', label: 'History' }
      ]}
    />
  {/if}
  <div class="flex items-end">
    <Button variant="outline" disabled={!ask.hasAskFilters} onclick={() => ask.clearAskFilters()}>
      <FilterX size={15} /> Clear
    </Button>
  </div>
</FilterBar>
