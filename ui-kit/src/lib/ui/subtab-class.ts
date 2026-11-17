// The look of one underline tab (Subtabs, SubtabButton). UI kit, step 3: from the HiroLeague admin's tokens.
// UI kit, step 7d: the tabs are shadcn-svelte's Tabs triggers; these classes keep the kit's underline (a 2px
// primary border under the picked one) in place of the trigger's own pill and bar.
import { cn } from '$kit/utils';

/** Outer row: tablist + optional trailing toolbar (on Tabs' root, which is a column by default). */
export const SUBTAB_STRIP_SHELL = '-mb-px flex min-h-[2.5rem] min-w-0 items-end gap-3 border-b border-border data-horizontal:flex-row';

/** Tablist row inside the strip. */
export const SUBTAB_TABLIST = 'flex h-auto min-h-9 w-auto min-w-0 flex-1 flex-wrap items-end justify-start gap-x-1 gap-y-0 rounded-none p-0';

/** One underline tab; the picked one is marked by its trigger's data-active. */
export function subtabClass(className?: string) {
	return cn(
		'-mb-px h-auto min-w-0 max-w-[min(22rem,calc(100vw-10rem))] flex-none shrink-0 justify-start truncate rounded-none border-0 border-b-2 border-transparent bg-transparent px-3 py-2 text-left text-sm font-normal text-muted-foreground shadow-none transition-colors after:hidden hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
		'data-active:border-primary data-active:bg-transparent data-active:font-semibold data-active:text-foreground data-active:shadow-none dark:data-active:border-primary dark:data-active:bg-transparent',
		// the trigger clears the picked tab's border on a line list in dark mode with this longer selector: match it
		'dark:group-data-[variant=line]/tabs-list:data-active:border-primary',
		className
	);
}
