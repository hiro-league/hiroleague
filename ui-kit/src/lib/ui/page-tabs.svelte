<script lang="ts" module>
	import type { Component } from 'svelte';

	export type CountTone = 'neutral' | 'primary' | 'ok' | 'warn' | 'error';

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
		/** The count's colour: neutral by default; a status tone when the number means something to act on. */
		countTone?: CountTone;
		title?: string;
		ariaLabel?: string;
		htmlId?: string;
		ariaControls?: string;
	};
</script>

<script lang="ts" generics="T extends string">
	// A page's tabs from a list, in the page header: the pill strip (the page's main tabs) or the underlined strip
	// (tabs inside a tab). It looks like shadcn's Tabs, and adds what a list of tabs needs: a tab that is a link, a
	// count beside a name (a small round badge, in its tone), and a place after the tabs for one more of the page's
	// own (an open record's tab).
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
		// dark: a blue tint, since the light pill's raised look is lost there (input/30 on muted was nearly the track's grey)
		default: 'bg-background text-foreground shadow-sm dark:border-primary/60 dark:bg-primary/30 dark:text-foreground',
		line: "text-foreground after:absolute after:inset-x-0 after:bottom-[-5px] after:h-0.5 after:bg-foreground dark:text-foreground"
	} as const;
	// Dark: a stronger fill and light words, since the faint tint and the tone's own text sank into the dark track
	const COUNT: Record<CountTone, string> = {
		neutral: 'bg-foreground/10 text-foreground/70 dark:bg-foreground/25 dark:text-foreground',
		primary: 'bg-primary/15 text-primary dark:bg-primary/60 dark:text-foreground',
		ok: 'bg-success/15 text-success dark:bg-success/30 dark:text-foreground',
		warn: 'bg-warning/15 text-warning dark:bg-warning/30 dark:text-warning',
		error: 'bg-destructive/15 text-destructive dark:bg-destructive/45 dark:text-foreground'
	};
</script>

{#snippet count(t: PageTab<T>)}
	{#if t.count !== undefined}<span
			class={cn('inline-flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[10px] leading-none font-semibold tabular-nums', COUNT[t.countTone ?? 'neutral'])}
			>{t.count}</span
		>{/if}
{/snippet}

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
				>{#if t.icon}<t.icon />{/if}{t.label}{@render count(t)}</a
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
				>{#if t.icon}<t.icon />{/if}{t.label}{@render count(t)}</button
			>
		{/if}
	{/each}
	{#if extra}{@render extra()}{/if}
</div>
