<script lang="ts">
  import type { KnowledgeDocument, KnowledgeIngestMetadata } from '$lib/api/knowledge';
  import Button from '$lib/components/ui/button.svelte';
  import * as Dialog from '$lib/components/ui/dialog';
  import CreatableCategorySelect from '$lib/features/knowledge/CreatableCategorySelect.svelte';
  import CreatableTagsSelect from '$lib/features/knowledge/CreatableTagsSelect.svelte';
  import KnowledgeAffectedDocumentsList from '$lib/features/knowledge/browse/KnowledgeAffectedDocumentsList.svelte';
  import type { KnowledgeBrowseModel } from '$lib/features/knowledge/state/knowledge-browse.svelte';
  import type { KnowledgeOptionsModel } from '$lib/features/knowledge/state/knowledge-options.svelte';
  import { optionalInt } from '$lib/features/knowledge/shared/knowledge-pure';
  import {
    KNOWLEDGE_BROWSE_BULK_DIALOG,
    KNOWLEDGE_BROWSE_BULK_DIALOG_AFFECTED_LIST,
    KNOWLEDGE_BROWSE_BULK_DIALOG_BODY,
    KNOWLEDGE_FIELD_LABEL,
    KNOWLEDGE_FIELD_LABEL_TEXT,
    KNOWLEDGE_SELECT
  } from '$lib/features/knowledge/shared/knowledge-ui';
  import { cn } from '$lib/utils';

  type Props = {
    open: boolean;
    documents: KnowledgeDocument[];
    browse: KnowledgeBrowseModel;
    options: KnowledgeOptionsModel;
    onSaved?: (result: { saved: number; failed: number }) => void;
  };

  let { open = $bindable(false), documents = [], browse, options, onSaved }: Props = $props();

  let ownerKind = $state<KnowledgeIngestMetadata['owner_kind']>('system');
  let ownerId = $state('0');
  let categoryId = $state('');
  let subcategoryId = $state('');
  let tags = $state<string[]>([]);
  let saving = $state(false);
  let saveError = $state<string | null>(null);

  const documentCount = $derived(documents.length);
  const subcategories = $derived(
    options.categories.filter((category) => category.parent_id === optionalInt(categoryId))
  );

  $effect(() => {
    if (!open || documents.length === 0) return;
    const document = documents[0];
    ownerKind = document.owner_kind as KnowledgeIngestMetadata['owner_kind'];
    ownerId = document.owner_id;
    categoryId = document.category_id != null ? String(document.category_id) : '';
    subcategoryId = document.subcategory_id != null ? String(document.subcategory_id) : '';
    tags = [...(document.tags ?? [])];
    saving = false;
    saveError = null;
  });

  function handleOwnerKindChange() {
    if (ownerKind === 'system') {
      ownerId = '0';
    } else if (ownerKind === 'character') {
      ownerId = String(options.characters[0]?.id ?? '');
    } else {
      ownerId = String(options.users[0]?.id ?? '');
    }
  }

  async function handleSave() {
    if (documents.length === 0 || saving) return;
    saving = true;
    saveError = null;
    const result = await browse.saveDocumentsMetadata(
      documents.map((document) => document.id),
      {
        owner_kind: ownerKind,
        owner_id: ownerId,
        category_id: optionalInt(categoryId),
        subcategory_id: optionalInt(subcategoryId),
        tags
      }
    );
    saving = false;
    if (result.saved > 0) {
      open = false;
      onSaved?.(result);
    } else {
      saveError = 'Metadata update failed.';
    }
  }
</script>

<Dialog.Root bind:open>
  <Dialog.Content class={KNOWLEDGE_BROWSE_BULK_DIALOG} showCloseButton={!saving}>
    <Dialog.Header>
      <Dialog.Title class="break-words">
        {documentCount === 1 ? 'Edit document metadata' : `Edit metadata for ${documentCount} documents`}
      </Dialog.Title>
      {#if documentCount > 1}
        <Dialog.Description>
          Changes apply to all selected documents. Initial values come from the first selected row.
        </Dialog.Description>
      {/if}
    </Dialog.Header>

    <div class={KNOWLEDGE_BROWSE_BULK_DIALOG_BODY}>
      <KnowledgeAffectedDocumentsList {documents} class={KNOWLEDGE_BROWSE_BULK_DIALOG_AFFECTED_LIST} />

      <div class="grid shrink-0 gap-3 overflow-visible">
      <div class="flex flex-wrap items-end gap-3">
        <label class={KNOWLEDGE_FIELD_LABEL}>
          <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Owner</span>
          <select
            class={cn(KNOWLEDGE_SELECT, 'w-[180px]')}
            bind:value={ownerKind}
            disabled={saving}
            onchange={handleOwnerKindChange}
          >
            <option value="system">System</option>
            <option value="character">Character</option>
            <option value="user">User</option>
          </select>
        </label>
        {#if ownerKind === 'character'}
          <label class={KNOWLEDGE_FIELD_LABEL}>
            <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Character</span>
            <select class={cn(KNOWLEDGE_SELECT, 'w-[220px]')} bind:value={ownerId} disabled={saving}>
              {#each options.characters as character (character.id)}
                <option value={String(character.id)}>{character.name} ({character.id})</option>
              {/each}
            </select>
          </label>
        {:else if ownerKind === 'user'}
          <label class={KNOWLEDGE_FIELD_LABEL}>
            <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>User</span>
            <select class={cn(KNOWLEDGE_SELECT, 'w-[220px]')} bind:value={ownerId} disabled={saving}>
              {#each options.users as user (user.id)}
                <option value={String(user.id)}>{user.name} ({user.id})</option>
              {/each}
            </select>
          </label>
        {/if}
        <label class={KNOWLEDGE_FIELD_LABEL}>
          <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Category</span>
          <CreatableCategorySelect
            bind:value={categoryId}
            options={options.topCategories}
            placeholder="None"
            searchPlaceholder="Search or create category…"
            creating={options.creatingCategory}
            disabled={saving}
            onSelect={() => {
              subcategoryId = '';
            }}
            onCreate={(name) => options.upsertCategoryByName(name, null)}
          />
        </label>
        <label class={KNOWLEDGE_FIELD_LABEL}>
          <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Subcategory</span>
          <CreatableCategorySelect
            bind:value={subcategoryId}
            options={subcategories}
            placeholder="None"
            searchPlaceholder="Search or create subcategory…"
            disabled={!categoryId || saving}
            creating={options.creatingSubcategory}
            onCreate={(name) => options.upsertCategoryByName(name, optionalInt(categoryId))}
          />
        </label>
        <label class="grid min-w-[280px] flex-1 gap-1 font-sans text-sm">
          <span class={KNOWLEDGE_FIELD_LABEL_TEXT}>Tags</span>
          <CreatableTagsSelect
            bind:selected={tags}
            options={options.tags}
            creating={options.creatingTag}
            disabled={saving}
            onCreate={options.upsertTag}
          />
        </label>
      </div>
      {#if saveError}
        <p class="font-sans text-sm text-destructive">{saveError}</p>
      {/if}
      </div>
    </div>

    <Dialog.Footer>
      <Button variant="outline" disabled={saving} onclick={() => (open = false)}>Cancel</Button>
      <Button disabled={saving || documents.length === 0} onclick={() => void handleSave()}>
        {saving ? 'Saving…' : documentCount === 1 ? 'Save metadata' : `Update ${documentCount} documents`}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
