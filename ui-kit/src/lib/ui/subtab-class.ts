// The look of one underline tab (Subtabs, SubtabButton). UI kit, step 3: from the HiroLeague admin's tokens.
import { cn } from '$kit/utils';

/** Outer row: tablist + optional trailing toolbar. */
export const SUBTAB_STRIP_SHELL = '-mb-px flex min-h-[2.5rem] min-w-0 items-end gap-3 border-b border-border';

/** Tablist row inside the strip. */
export const SUBTAB_TABLIST = 'flex min-h-9 min-w-0 flex-1 flex-wrap items-end gap-x-1 gap-y-0';

/** One underline tab; `active` for the selected one. */
export function subtabClass(active: boolean, className?: string) {
	return cn(
		'-mb-px min-w-0 max-w-[min(22rem,calc(100vw-10rem))] shrink-0 truncate border-b-2 border-transparent bg-transparent px-3 py-2 text-left text-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
		active && 'border-primary font-semibold text-foreground',
		className
	);
}
