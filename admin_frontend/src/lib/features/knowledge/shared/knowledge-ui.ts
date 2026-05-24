/**
 * Shared Tailwind/class strings for Knowledge admin UI.
 *
 * Header / sticky-page / tablist tokens now live in `$lib/styling/admin-tokens`.
 * Form tokens re-export admin tokens so Knowledge inputs stay aligned app-wide.
 */
import { cn } from '$lib/utils';
import {
  ADMIN_INPUT,
  ADMIN_INPUT_LG,
  ADMIN_SELECT,
  ADMIN_SELECT_LG
} from '$lib/styling/admin-tokens';

export const KNOWLEDGE_SECTION_CARD = 'rounded-md border bg-card p-4 shadow-sm';

export const KNOWLEDGE_SECTION_TITLE = 'font-sans text-base font-semibold text-primary';

export const KNOWLEDGE_FIELD_LABEL = 'grid gap-1 font-sans text-sm';

export const KNOWLEDGE_FIELD_LABEL_TEXT = 'font-medium';

export const KNOWLEDGE_INPUT = ADMIN_INPUT;

export const KNOWLEDGE_INPUT_LG = ADMIN_INPUT_LG;

export const KNOWLEDGE_SELECT = ADMIN_SELECT;

export const KNOWLEDGE_SELECT_LG = ADMIN_SELECT_LG;

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
