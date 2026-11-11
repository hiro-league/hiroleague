/** Shared Tailwind/class strings for Knowledge admin UI. */

export const KNOWLEDGE_SECTION_CARD = 'rounded-md border bg-card p-4 shadow-sm';

export const KNOWLEDGE_SECTION_TITLE = 'font-sans text-base font-semibold text-primary';

export const KNOWLEDGE_FIELD_LABEL = 'grid gap-1 font-sans text-sm';

export const KNOWLEDGE_FIELD_LABEL_TEXT = 'font-medium';

export const KNOWLEDGE_METADATA_SHELL = 'grid gap-2 rounded-md border bg-background p-3';

export const KNOWLEDGE_TABLE_HEAD = 'sticky top-0 bg-muted text-xs uppercase text-muted-foreground';

/** Bulk browse actions (metadata / re-ingest / delete) — wide, content-sized up to viewport max. */
export const KNOWLEDGE_BROWSE_BULK_DIALOG =
  'flex w-[min(92vw,720px)] max-w-[min(92vw,720px)] max-h-[min(85vh,720px)] flex-col gap-4 overflow-hidden sm:max-w-[min(92vw,720px)]';

/** Scrolls only when dialog content exceeds the viewport cap. */
export const KNOWLEDGE_BROWSE_BULK_DIALOG_BODY = 'flex min-h-0 shrink flex-col gap-3 overflow-y-auto';

/** Content-sized list shell — scroll only when many documents (max height on the `<ul>`). */
export const KNOWLEDGE_BROWSE_BULK_DIALOG_AFFECTED_LIST =
  'shrink-0 rounded-md border bg-muted/30 p-3';

/** Ask tab collapsible section bodies (`aria-controls` targets). */
export const KNOWLEDGE_ASK_QUESTION_BODY_ID = 'knowledge-ask-question';
export const KNOWLEDGE_ASK_CHUNK_RESULTS_BODY_ID = 'knowledge-ask-chunk-results';
