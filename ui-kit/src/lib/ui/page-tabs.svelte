<script lang="ts" module>
	import type { Component } from 'svelte';

	/** One tab of a page. With `href` it is a real link (it can be opened in a new tab or copied); else picking it
	 * calls `onchange`. `kind` is only read for its meaning by the app that wrote the list. */
	export type PageTab<T extends string = string> = {
		id: T;
		label: string;
		// eslint-disable-next-line @typescript-eslint/no-explicit-any -- any icon component (lucide's, or an app's own)
		icon?: Component<any>;
		href?: string;
		kind?: 'pane' | 'route';
		disabled?: boolean;
		count?: number | string;
		title?: string;
		ariaLabel?: string;
		htmlId?: string;
		ariaControls?: string;
	};
</script>

<script lang="ts" generics="T extends string">
	// A page's tabs from a list, in the page header: the pill strip (the page's main tabs) or the underlined strip
	// (tabs inside a tab). It looks like shadcn's Tabs, and adds what a list of tabs needs: a tab that is a link, a
	// count beside a name, and a place after the tabs for one more of the page's own (an open record's tab).
	// UI kit, step 3: from the HiroLeague admin's AdminTabStrip, on the kit's look.
	import type { Snippet } from 'svelte';
	import { cn } from '$kit/utils';

	interface Props {
		tabs: readonly PageTab<T>[];
		value: T;
		onchange?: (id: T) => void;
		label: string; // what the tabs choose, for screen readers
		variant?: 'default' | 'line';
		class?: string;
		extra?: Snippet;
	}
	let { tabs, value, onchange, label, variant = 'default', class: className, extra }: Props = $props();

	const TAB =
		"relative inline-flex h-[calc(100%_-_1px)] items-center justify-center gap-1.5 rounded-md border border-transparent px-2 py-0.5 text-sm font-medium whitespace-nowrap text-foreground/60 transition-all hover:text-foreground focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none aria-disabled:pointer-events-none aria-disabled:opacity-50 dark:text-muted-foreground dark:hover:text-foreground [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4";
	const ON = {
		default: 'bg-background text-foreground shadow-sm dark:border-input dark:bg-input/30 dark:text-foreground',
		line: "text-foreground after:absolute after:inset-x-0 after:bottom-[-5px] after:h-0.5 after:bg-foreground dark:text-foreground"
	} as const;
</script>

<div
	class={cn('inline-flex h-8 w-fit max-w-full items-center text-muted-foreground', variant === 'default' ? 'rounded-lg bg-muted p-[3px]' : 'gap-1', className)}
	role="tablist"
	aria-label={label}
>
	{#each tabs as t (t.id)}
		{@const on = t.id === value}
		{#if t.href}
			<a
				id={t.htmlId}
				href={t.disabled ? undefined : t.href}
				role="tab"
				aria-selected={on}
				aria-disabled={t.disabled}
				aria-label={t.ariaLabel}
				aria-controls={t.ariaControls}
				title={t.title}
				class={cn(TAB, on && ON[variant])}
				>{#if t.icon}<t.icon />{/if}{t.label}{#if t.count !== undefined}<span class="text-xs text-muted-foreground tabular-nums">({t.count})</span>{/if}</a
			>
		{:else}
			<button
				type="button"
				id={t.htmlId}
				role="tab"
				aria-selected={on}
				aria-disabled={t.disabled}
				aria-label={t.ariaLabel}
				aria-controls={t.ariaControls}
				title={t.title}
				disabled={t.disabled}
				class={cn(TAB, on && ON[variant])}
				onclick={() => onchange?.(t.id)}
				>{#if t.icon}<t.icon />{/if}{t.label}{#if t.count !== undefined}<span class="text-xs text-muted-foreground tabular-nums">({t.count})</span>{/if}</button
			>
		{/if}
	{/each}
	{#if extra}{@render extra()}{/if}
</div>
