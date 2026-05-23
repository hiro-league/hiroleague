/** Shared Tailwind/class strings for Knowledge admin UI. */
import { cn } from '$lib/utils';

export const KNOWLEDGE_HEADER_KICKER = 'font-sans text-xs font-extrabold uppercase text-primary';

export const KNOWLEDGE_HEADER_TITLE = 'brand-text-gradient mt-1 text-3xl font-semibold';

export const KNOWLEDGE_HEADER_INTRO = 'font-sans text-sm text-muted-foreground';

/** Sticks below the admin shell header (4rem) while scrolling page content. */
export const KNOWLEDGE_PAGE_STICKY_HEADER =
  'sticky top-16 z-10 -mx-4 border-b border-border/70 bg-background/95 px-4 pb-4 backdrop-blur supports-[backdrop-filter]:bg-background/85 md:-mx-6 md:px-6';

export const KNOWLEDGE_TABLIST_SHELL = 'inline-flex rounded-lg border bg-card p-1';

export const KNOWLEDGE_SECTION_CARD = 'rounded-md border bg-card p-4 shadow-sm';

export const KNOWLEDGE_SECTION_TITLE = 'font-sans text-base font-semibold text-primary';

export const KNOWLEDGE_FIELD_LABEL = 'grid gap-1 font-sans text-sm';

export const KNOWLEDGE_FIELD_LABEL_TEXT = 'font-medium';

export const KNOWLEDGE_INPUT =
  'h-9 rounded-md border bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-primary';

export const KNOWLEDGE_INPUT_LG =
  'h-10 rounded-md border bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-primary';

export const KNOWLEDGE_SELECT = KNOWLEDGE_INPUT;

export const KNOWLEDGE_SELECT_LG = KNOWLEDGE_INPUT_LG;

export const KNOWLEDGE_METADATA_SHELL = 'grid gap-2 rounded-md border bg-background p-3';

export const KNOWLEDGE_TABLE = 'w-full text-left font-sans text-sm';

export const KNOWLEDGE_TABLE_HEAD = 'sticky top-0 bg-muted text-xs uppercase text-muted-foreground';

export function cnKnowledgeBrowseDocRow(selected: boolean) {
  return cn(
    'cursor-pointer border-t transition-[background-color,box-shadow]',
    'hover:bg-primary/10 hover:shadow-[inset_0_0_0_2px] hover:shadow-brand',
    selected && 'bg-primary/10 shadow-[inset_0_0_0_2px] shadow-primary'
  );
}

export function cnKnowledgeTab(active: boolean) {
  return cn('shadow-none', !active && 'bg-transparent text-muted-foreground hover:bg-secondary');
}
