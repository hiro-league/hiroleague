<script lang="ts">
  import { FilterX } from '@lucide/svelte';
  import AdminFilterBar from '$lib/components/page/table/AdminFilterBar.svelte';
  import SearchInput from '$lib/search/SearchInput.svelte';
  import AdminFilterBarSelect from '$lib/components/page/table/AdminFilterBarSelect.svelte';
  import Button from '$lib/components/ui/button.svelte';
  import FormField from '$lib/components/ui/form-field.svelte';
  import CreatableCategorySelect from '$lib/features/knowledge/shared/CreatableCategorySelect.svelte';
  import CreatableTagsSelect from '$lib/features/knowledge/shared/CreatableTagsSelect.svelte';
  import type { KnowledgeBrowseModel } from '$lib/features/knowledge/state/knowledge-browse.svelte';
  import type { KnowledgeOptionsModel } from '$lib/features/knowledge/state/knowledge-options.svelte';
  import { optionalInt } from '$lib/features/knowledge/shared/knowledge-pure';

  type Props = {
    browse: KnowledgeBrowseModel;
    options: KnowledgeOptionsModel;
  };

  let { browse, options }: Props = $props();

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
  <SearchInput
    label="Title"
    value={browse.browseTitle}
    onValueChange={(v) => (browse.browseTitle = v)}
    placeholder="Search title"
    class="w-[10rem] shrink-0"
  />
  <AdminFilterBarSelect
    label="Status"
    bind:value={browse.browseStatus}
    placeholder="Any"
    class="w-[9rem] shrink-0"
    options={[
      { value: 'pending', label: 'Pending' },
      { value: 'parsing', label: 'Parsing' },
      { value: 'embedding', label: 'Embedding' },
      { value: 'ready', label: 'Ready' },
      { value: 'failed', label: 'Failed' }
    ]}
  />
  <AdminFilterBarSelect
    label="Owner"
    bind:value={browse.browseOwnerKind}
    placeholder="Any"
    class="w-[9rem] shrink-0"
    onValueChange={() => browse.handleBrowseOwnerKindChange()}
    options={[
      { value: 'system', label: 'System' },
      { value: 'character', label: 'Character' },
      { value: 'user', label: 'User' }
    ]}
  />
  {#if browse.browseOwnerKind === 'character'}
    <AdminFilterBarSelect
      label="Character"
      bind:value={browse.browseOwnerId}
      class="w-[11rem] shrink-0"
      options={characterFilterOptions}
    />
  {:else if browse.browseOwnerKind === 'user'}
    <AdminFilterBarSelect
      label="User"
      bind:value={browse.browseOwnerId}
      class="w-[11rem] shrink-0"
      options={userFilterOptions}
    />
  {/if}
  <FormField label="Category" class="w-[11rem] shrink-0">
    <CreatableCategorySelect
      bind:value={browse.browseCategoryId}
      options={options.topCategories}
      placeholder="Any"
      searchPlaceholder="Search or create category…"
      creating={options.creatingCategory}
      class="w-full"
      onSelect={() => {
        browse.browseSubcategoryId = '';
      }}
      onCreate={(name) => options.upsertCategoryByName(name, null)}
    />
  </FormField>
  <FormField label="Subcategory" class="w-[11rem] shrink-0">
    <CreatableCategorySelect
      bind:value={browse.browseSubcategoryId}
      options={browse.browseSubcategories}
      placeholder="Any"
      searchPlaceholder="Search or create subcategory…"
      disabled={!browse.browseCategoryId}
      creating={options.creatingSubcategory}
      class="w-full"
      onCreate={(name) => options.upsertCategoryByName(name, optionalInt(browse.browseCategoryId))}
    />
  </FormField>
  <label class="grid w-[12rem] shrink-0 gap-1.5 text-left">
    <span class="font-sans text-sm font-semibold leading-snug text-muted-foreground">Tags</span>
    <CreatableTagsSelect
      bind:selected={browse.browseTags}
      options={options.tags}
      creating={options.creatingTag}
      class="w-full"
      onCreate={options.upsertTag}
    />
  </label>
  <div class="flex items-end">
    <Button variant="outline" disabled={!browse.hasBrowseFilters} onclick={() => browse.clearBrowseFilters()}>
      <FilterX size={15} /> Clear
    </Button>
  </div>
</AdminFilterBar>
