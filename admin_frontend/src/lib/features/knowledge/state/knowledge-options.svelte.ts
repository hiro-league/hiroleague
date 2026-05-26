import {
  createKnowledgeCategory,
  createKnowledgeTag,
  getKnowledgeOptions,
  type KnowledgeCategory,
  type KnowledgeOwnerOption
} from '$lib/api/knowledge';

/** Shared taxonomy and owner picklists (ingest + browse + ask). */
export function createKnowledgeOptionsModel(deps: { setError: (message: string | null) => void }) {
  let categories = $state<KnowledgeCategory[]>([]);
  let tags = $state<{ id: number; name: string }[]>([]);
  let characters = $state<KnowledgeOwnerOption[]>([]);
  let users = $state<KnowledgeOwnerOption[]>([]);
  let rewriteDefaultOn = $state(false);
  let creatingCategory = $state(false);
  let creatingSubcategory = $state(false);
  let creatingTag = $state(false);

  const topCategories = $derived(categories.filter((category) => category.parent_id === null));

  function categoryLabel(id: number | null): string {
    if (id === null) return '';
    return categories.find((category) => category.id === id)?.name ?? String(id);
  }

  async function loadOptions() {
    try {
      const payload = await getKnowledgeOptions();
      categories = payload.data.categories;
      tags = payload.data.tags;
      characters = payload.data.characters;
      users = payload.data.users;
      rewriteDefaultOn = payload.data.rewrite_default_on ?? false;
    } catch (err) {
      deps.setError(err instanceof Error ? err.message : 'Could not load knowledge options.');
    }
  }

  async function upsertCategoryByName(name: string, parentId: number | null): Promise<KnowledgeCategory> {
    if (parentId === null) creatingCategory = true;
    else creatingSubcategory = true;
    deps.setError(null);
    try {
      const payload = await createKnowledgeCategory(name.trim(), parentId);
      categories = [...categories.filter((category) => category.id !== payload.data.id), payload.data].sort((a, b) =>
        a.name.localeCompare(b.name)
      );
      return payload.data;
    } catch (err) {
      deps.setError(err instanceof Error ? err.message : 'Could not create category.');
      throw err;
    } finally {
      creatingCategory = false;
      creatingSubcategory = false;
    }
  }

  async function upsertTag(name: string): Promise<{ name: string }> {
    const clean = name.trim();
    if (!clean) throw new Error('Tag name is required.');
    creatingTag = true;
    deps.setError(null);
    try {
      const payload = await createKnowledgeTag(clean);
      tags = [...tags.filter((tag) => tag.id !== payload.data.id), payload.data].sort((a, b) =>
        a.name.localeCompare(b.name)
      );
      return payload.data;
    } catch (err) {
      deps.setError(err instanceof Error ? err.message : 'Could not create tag.');
      throw err;
    } finally {
      creatingTag = false;
    }
  }

  return {
    get categories() {
      return categories;
    },
    get tags() {
      return tags;
    },
    get characters() {
      return characters;
    },
    get users() {
      return users;
    },
    get rewriteDefaultOn() {
      return rewriteDefaultOn;
    },
    get creatingCategory() {
      return creatingCategory;
    },
    get creatingSubcategory() {
      return creatingSubcategory;
    },
    get creatingTag() {
      return creatingTag;
    },
    get topCategories() {
      return topCategories;
    },
    categoryLabel,
    loadOptions,
    upsertCategoryByName,
    upsertTag
  };
}

export type KnowledgeOptionsModel = ReturnType<typeof createKnowledgeOptionsModel>;
