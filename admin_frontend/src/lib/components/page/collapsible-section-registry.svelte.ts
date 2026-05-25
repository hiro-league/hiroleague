/** Context key for optional bulk expand/collapse of `<SectionCardMuted collapsible>`. */
export const COLLAPSIBLE_SECTION_REGISTRY = Symbol('collapsible-section-registry');

type CollapsibleSectionEntry = {
  getExpanded: () => boolean;
  setExpanded: (next: boolean) => void;
};

export type CollapsibleSectionRegistry = {
  register: (entry: CollapsibleSectionEntry) => () => void;
  expandAll: () => void;
  collapseAll: () => void;
  toggleAll: () => void;
  /** Call after a single card toggles so toolbar affordances stay in sync. */
  notifyChanged: () => void;
  readonly anyExpanded: boolean;
};

export function createCollapsibleSectionRegistry(): CollapsibleSectionRegistry {
  const entries = new Set<CollapsibleSectionEntry>();
  let revision = $state(0);

  function notifyChanged() {
    revision += 1;
  }

  function register(entry: CollapsibleSectionEntry) {
    entries.add(entry);
    notifyChanged();
    return () => {
      entries.delete(entry);
      notifyChanged();
    };
  }

  function expandAll() {
    for (const entry of entries) {
      entry.setExpanded(true);
    }
    notifyChanged();
  }

  function collapseAll() {
    for (const entry of entries) {
      entry.setExpanded(false);
    }
    notifyChanged();
  }

  const anyExpanded = $derived.by(() => {
    revision;
    for (const entry of entries) {
      if (entry.getExpanded()) return true;
    }
    return false;
  });

  function toggleAll() {
    if (anyExpanded) collapseAll();
    else expandAll();
  }

  return {
    register,
    expandAll,
    collapseAll,
    toggleAll,
    notifyChanged,
    get anyExpanded() {
      return anyExpanded;
    }
  };
}
